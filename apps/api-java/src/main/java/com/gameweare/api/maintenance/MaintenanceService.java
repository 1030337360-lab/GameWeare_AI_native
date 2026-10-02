package com.gameweare.api.maintenance;

import com.gameweare.api.create.CreateController;
import com.gameweare.api.create.CreateService;
import io.minio.MinioClient;
import io.minio.RemoveObjectArgs;
import jakarta.servlet.http.HttpServletRequest;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@Service
class MaintenanceService {
    private final JdbcTemplate jdbc;
    private final MinioClient minio;
    private final CreateService creation;
    @org.springframework.beans.factory.annotation.Autowired(required = false)
    private com.gameweare.api.catalog.GameCatalogCache gameCache;
    @org.springframework.beans.factory.annotation.Autowired(required = false)
    private com.gameweare.api.catalog.GameTrendingService trending;
    MaintenanceService(JdbcTemplate jdbc, MinioClient minio, CreateService creation) {
        this.jdbc=jdbc; this.minio=minio; this.creation=creation;
    }

    public Map<String, Object> overview(String actor) {
        authorize(actor);
        Map<String, Long> counts = new LinkedHashMap<>();
        for (var row : jdbc.queryForList("SELECT status,COUNT(*) AS n FROM create_jobs WHERE deleted_at IS NULL GROUP BY status"))
            counts.put(row.get("status").toString(), ((Number) row.get("n")).longValue());
        var assets = jdbc.queryForMap("SELECT COUNT(*) AS n,COALESCE(SUM(size_bytes),0) AS bytes FROM assets");
        return Map.of("jobCounts", counts,
                "failedJobsLast24h", count("SELECT COUNT(*) FROM create_jobs WHERE status='failed' AND deleted_at IS NULL AND updated_at>=DATE_SUB(UTC_TIMESTAMP(),INTERVAL 24 HOUR)"),
                "pendingReviews", count("SELECT COUNT(*) FROM moderation_reviews WHERE status='pending'"),
                "publicGames", count("SELECT COUNT(*) FROM games WHERE publish_status='published' AND visibility='public'"),
                "assetsTotal", ((Number) assets.get("n")).longValue(), "assetsBytes", ((Number) assets.get("bytes")).longValue(),
                "recentFailedJobs", jobs(actor,"failed",5));
    }

    public List<Map<String, Object>> jobs(String actor, String status, int limit) {
        authorize(actor);
        String sql = """
            SELECT j.id,j.status,j.error_message,j.prompt,j.user_id,u.email AS creator_email,g.slug AS game_slug,
                   COALESCE(g.title,p.title) AS display_title,
                   j.created_at,j.updated_at,
                   (SELECT s.stage FROM create_run_steps s WHERE s.job_id=j.id ORDER BY s.step_no DESC LIMIT 1) AS current_stage
            FROM create_jobs j JOIN users u ON u.id=j.user_id JOIN create_projects p ON p.id=j.project_id
            LEFT JOIN games g ON g.id=p.game_id
            WHERE j.deleted_at IS NULL
            """;
        List<Object> args = new ArrayList<>();
        if (status != null && !status.isBlank()) { sql += " AND j.status=?"; args.add(status); }
        sql += " ORDER BY j.created_at DESC LIMIT ?"; args.add(limit(limit));
        return jdbc.query(sql, (rs,n) -> {
            Map<String,Object> m = new LinkedHashMap<>();
            m.put("id",rs.getString("id")); m.put("status",rs.getString("status"));
            m.put("currentStage",rs.getString("current_stage")); m.put("errorCode",null);
            m.put("errorMessage",rs.getString("error_message"));
            m.put("promptSummary",sanitize(rs.getString("prompt"),220));
            m.put("displayTitle",rs.getString("display_title"));
            m.put("creatorId",rs.getString("user_id")); m.put("creatorEmail",rs.getString("creator_email"));
            m.put("gameSlug",rs.getString("game_slug")); m.put("createdAt",rs.getTimestamp("created_at"));
            m.put("updatedAt",rs.getTimestamp("updated_at")); return m;
        }, args.toArray());
    }

    /** Read-only administrator view of the persisted execution trail. Never return prompts sent to the provider or credentials. */
    public Map<String, Object> jobTrace(String actor, String id) {
        authorize(actor);
        var jobs = jdbc.queryForList("""
            SELECT j.id,j.status,j.engine,j.agent_mode,j.create_type,j.project_id,j.game_id,j.prompt,
                   j.error_message,j.reserved_tokens,j.actual_tokens,j.attempts,j.created_at,j.updated_at,
                   u.email AS creator_email,g.slug AS game_slug,g.publish_status
            FROM create_jobs j JOIN users u ON u.id=j.user_id LEFT JOIN games g ON g.id=j.game_id
            WHERE j.id=? AND j.deleted_at IS NULL
            """, id);
        if (jobs.isEmpty()) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Job not found");
        var j = jobs.get(0);
        Map<String, Object> result = new LinkedHashMap<>();
        for (String field : List.of("id", "status", "engine", "project_id", "game_id", "reserved_tokens",
                "actual_tokens", "attempts", "created_at", "updated_at", "creator_email", "game_slug", "publish_status")) {
            String output = switch (field) {
                case "project_id" -> "projectId"; case "game_id" -> "gameId";
                case "reserved_tokens" -> "reservedTokens"; case "actual_tokens" -> "actualTokens";
                case "created_at" -> "createdAt"; case "updated_at" -> "updatedAt";
                case "creator_email" -> "creatorEmail"; case "game_slug" -> "gameSlug";
                case "publish_status" -> "publishStatus"; default -> field;
            };
            result.put(output, j.get(field));
        }
        result.put("agentMode", j.get("agent_mode"));
        result.put("createType", j.get("create_type"));
        result.put("promptSummary", sanitize((String) j.get("prompt"), 500));
        result.put("errorMessage", sanitize((String) j.get("error_message"), 3500));
        result.put("steps", jdbc.query("""
            SELECT step_no,stage,status,message,created_at FROM create_run_steps
            WHERE job_id=? ORDER BY step_no LIMIT 200
            """, (rs, n) -> {
            Map<String, Object> step = new LinkedHashMap<>();
            step.put("stepNo", rs.getInt("step_no"));
            step.put("stage", rs.getString("stage"));
            step.put("status", rs.getString("status"));
            step.put("message", sanitize(rs.getString("message"), 3500));
            step.put("createdAt", rs.getTimestamp("created_at"));
            return step;
        }, id));
        result.put("modelCalls", jdbc.query("""
            SELECT id,model,state,prompt_tokens,completion_tokens,started_at,ended_at
            FROM agent_model_calls WHERE job_id=? ORDER BY started_at LIMIT 100
            """, (rs, n) -> {
            Map<String, Object> call = new LinkedHashMap<>();
            call.put("id", rs.getString("id"));
            call.put("model", rs.getString("model"));
            call.put("state", rs.getString("state"));
            call.put("promptTokens", rs.getObject("prompt_tokens"));
            call.put("completionTokens", rs.getObject("completion_tokens"));
            call.put("startedAt", rs.getTimestamp("started_at"));
            call.put("endedAt", rs.getTimestamp("ended_at"));
            return call;
        }, id));
        var workflows = jdbc.queryForList("""
            SELECT phase,prompt_tokens,completion_tokens,used_tokens FROM create_job_workflows WHERE job_id=?
            """, id);
        if (!workflows.isEmpty()) {
            var workflow = workflows.get(0);
            result.put("workflow", Map.of("phase", workflow.get("phase"),
                    "promptTokens", workflow.get("prompt_tokens"),
                    "completionTokens", workflow.get("completion_tokens"),
                    "usedTokens", workflow.get("used_tokens")));
        }
        return result;
    }

    public List<Map<String,Object>> failed(String actor, int limit) {
        authorize(actor);
        List<Map<String,Object>> output = new ArrayList<>();
        for (var j : jdbc.queryForList("""
            SELECT j.id,j.project_id,p.title AS project_title,j.create_type,j.agent_mode,j.status,j.error_message,
                   j.prompt,j.created_at,j.updated_at,u.email,g.slug AS game_slug
            FROM create_jobs j JOIN create_projects p ON p.id=j.project_id JOIN users u ON u.id=j.user_id
            LEFT JOIN games g ON g.id=j.game_id WHERE j.status='failed' AND j.deleted_at IS NULL
            ORDER BY j.updated_at DESC LIMIT ?
            """, limit(limit))) {
            String id = j.get("id").toString();
            List<Map<String,Object>> steps = new ArrayList<>();
            for (var s : jdbc.queryForList("SELECT step_no,stage,status,message,created_at FROM create_run_steps WHERE job_id=? ORDER BY step_no",id)) {
                Map<String,Object> step = new LinkedHashMap<>();
                step.put("stepNo",s.get("step_no")); step.put("stage",s.get("stage")); step.put("status",s.get("status"));
                step.put("inputSummary",null); step.put("outputSummary",sanitize((String)s.get("message"),3500));
                step.put("metrics",Map.of()); step.put("outputTokens",null); step.put("createdAt",s.get("created_at")); steps.add(step);
            }
            Map<String,Object> run = new LinkedHashMap<>();
            run.put("runId",id); run.put("jobId",id); run.put("projectId",j.get("project_id"));
            run.put("projectTitle",j.get("project_title")); run.put("createType",j.get("create_type"));
            run.put("agentMode",j.get("agent_mode")); run.put("status",j.get("status"));
            run.put("jobStatus",j.get("status")); run.put("errorCode",null); run.put("errorMessage",j.get("error_message"));
            run.put("promptSummary",sanitize((String)j.get("prompt"),220)); run.put("creatorEmail",j.get("email"));
            run.put("gameSlug",j.get("game_slug")); run.put("totalOutputTokens",0); run.put("startedAt",j.get("created_at"));
            run.put("completedAt",j.get("updated_at")); run.put("steps",steps); output.add(run);
        }
        return output;
    }

    @Transactional
    public Map<String,Object> reviewJob(String actor, String id, String reason) {
        authorize(actor);
        if (count("SELECT COUNT(*) FROM create_jobs WHERE id=? AND deleted_at IS NULL",id)==0) throw new ResponseStatusException(HttpStatus.NOT_FOUND,"Job not found");
        return review(actor,"job",id,"reviewed",reason);
    }

    @Transactional
    public Map<String,Object> retry(String actor, String id) {
        authorize(actor);
        var rows = jdbc.queryForList("SELECT user_id,project_id,prompt,agent_mode,create_type FROM create_jobs WHERE id=? AND status='failed' AND deleted_at IS NULL",id);
        if (rows.isEmpty()) throw new ResponseStatusException(HttpStatus.CONFLICT,"Only failed jobs can be retried");
        var j=rows.get(0);
        var request = new CreateController.JobRequest(j.get("prompt").toString(),List.of(),List.of(),
                j.get("agent_mode").toString(),j.get("create_type").toString(),j.get("project_id").toString());
        Map<String,Object> newJob = creation.create(j.get("user_id").toString(),request,null);
        audit(actor,"maintenance.job.retried","job",id,"{\"newJobId\":\""+newJob.get("id")+"\"}");
        return newJob;
    }

    public List<Map<String,Object>> games(String actor,String status,String query,int limit) {
        authorize(actor);
        String sql="SELECT * FROM games WHERE publish_status<>'deleted'";
        List<Object> args=new ArrayList<>();
        if(status!=null&&!status.isBlank()){sql+=" AND publish_status=?";args.add(status);}
        if(query!=null&&!query.isBlank()){sql+=" AND (title LIKE ? OR slug LIKE ?)";String q="%"+query.trim()+"%";args.add(q);args.add(q);}
        sql+=" ORDER BY updated_at DESC LIMIT ?";args.add(limit(limit));
        return jdbc.query(sql,(rs,n)->game(rs.getString("id"),rs.getString("slug"),rs.getString("title"),
                rs.getString("description"),rs.getString("visibility"),rs.getString("publish_status"),
                rs.getLong("plays_count"),rs.getLong("likes_count"),rs.getLong("favorites_count"),
                rs.getString("author_id"),rs.getTimestamp("updated_at")),args.toArray());
    }

    @Transactional
    public Map<String,Object> updateGame(String actor,String id,Map<String,String> body) {
        authorize(actor);
        if(body==null) throw new ResponseStatusException(HttpStatus.BAD_REQUEST,"Body required");
        List<String> fields=new ArrayList<>(); List<Object> values=new ArrayList<>();
        for(var entry:Map.of("title","title","description","description","visibility","visibility","publishStatus","publish_status").entrySet()){
            String value=body.get(entry.getKey());
            if(value==null)continue;
            if("title".equals(entry.getKey())&&(value.isBlank()||value.length()>255)) throw new ResponseStatusException(HttpStatus.BAD_REQUEST,"Invalid title");
            if("visibility".equals(entry.getKey())&&!Set.of("private","unlisted","public").contains(value)) throw new ResponseStatusException(HttpStatus.BAD_REQUEST,"Invalid visibility");
            if("publishStatus".equals(entry.getKey())&&!Set.of("draft","reviewing","published","rejected","archived").contains(value)) throw new ResponseStatusException(HttpStatus.BAD_REQUEST,"Invalid publish status");
            fields.add(entry.getValue()+"=?"); values.add(value);
        }
        if(!fields.isEmpty()){
            values.add(id);
            int changed=jdbc.update("UPDATE games SET "+String.join(",",fields)+" WHERE id=? AND publish_status<>'deleted'",values.toArray());
            if(changed==0) throw new ResponseStatusException(HttpStatus.NOT_FOUND,"Game not found");
            audit(actor,"maintenance.game.updated","game",id,"{}");
            projectGame(id);
        }
        return oneGame(id);
    }

    @Transactional
    public Map<String,Object> moderate(String actor,String id,Map<String,String> body) {
        authorize(actor);
        String status=body==null?null:body.get("status");
        if(status==null||!Set.of("approved","rejected").contains(status)) throw new ResponseStatusException(HttpStatus.BAD_REQUEST,"Invalid moderation status");
        if(count("SELECT COUNT(*) FROM games WHERE id=? AND publish_status<>'deleted'",id)==0) throw new ResponseStatusException(HttpStatus.NOT_FOUND,"Game not found");
        if("rejected".equals(status)) jdbc.update("UPDATE games SET publish_status='rejected',visibility='private' WHERE id=?",id);
        if("rejected".equals(status)) projectGame(id);
        return review(actor,"game",id,status,body.getOrDefault("reason",""));
    }

    private void projectGame(String id) {
        Runnable updateProjection = () -> {
            if (gameCache != null) {
                String slug = jdbc.queryForObject("SELECT slug FROM games WHERE id=?", String.class, id);
                gameCache.invalidate(slug);
            }
            if (trending != null) trending.refresh(id);
        };
        if (org.springframework.transaction.support.TransactionSynchronizationManager.isSynchronizationActive())
            org.springframework.transaction.support.TransactionSynchronizationManager.registerSynchronization(
                new org.springframework.transaction.support.TransactionSynchronization() {
                    @Override public void afterCommit() {
                        updateProjection.run();
                    }
                });
        else updateProjection.run();
    }

    public List<Map<String,Object>> assets(String actor,String gameId,String jobId,int limit){
        authorize(actor);
        String sql="SELECT * FROM assets WHERE 1=1";List<Object> args=new ArrayList<>();
        if(gameId!=null&&!gameId.isBlank()){sql+=" AND game_id=?";args.add(gameId);}
        if(jobId!=null&&!jobId.isBlank()){sql+=" AND job_id=?";args.add(jobId);}
        sql+=" ORDER BY created_at DESC LIMIT ?";args.add(limit(limit));
        return jdbc.query(sql,(rs,n)->{
            Map<String,Object> m=new LinkedHashMap<>();
            for(var pair:Map.ofEntries(Map.entry("id","id"),Map.entry("kind","kind"),Map.entry("bucket","bucket"),
                    Map.entry("objectKey","object_key"),Map.entry("publicUrl","public_url"),Map.entry("contentType","content_type"),
                    Map.entry("sizeBytes","size_bytes"),Map.entry("gameId","game_id"),Map.entry("versionId","version_id"),
                    Map.entry("jobId","job_id"),Map.entry("createdAt","created_at")).entrySet())m.put(pair.getKey(),rs.getObject(pair.getValue()));
            return m;
        },args.toArray());
    }

    public Map<String,Object> deleteAsset(String actor,String id){
        authorize(actor);
        var rows=jdbc.queryForList("SELECT bucket,object_key FROM assets WHERE id=?",id);
        if(rows.isEmpty())throw new ResponseStatusException(HttpStatus.NOT_FOUND,"Asset not found");
        String key=rows.get(0).get("object_key").toString();String bucket=rows.get(0).get("bucket").toString();
        if(count("SELECT COUNT(*) FROM games WHERE cover_object_key=?",key)>0 ||
           count("SELECT COUNT(*) FROM game_versions WHERE entry_object_key=? OR manifest_object_key=?",key,key)>0)
            throw new ResponseStatusException(HttpStatus.CONFLICT,"Asset is in use");
        try{minio.removeObject(RemoveObjectArgs.builder().bucket(bucket).object(key).build());}
        catch(Exception e){throw new ResponseStatusException(HttpStatus.BAD_GATEWAY,"Object storage unavailable",e);}
        jdbc.update("DELETE FROM assets WHERE id=?",id);
        audit(actor,"maintenance.asset.deleted","asset",id,"{}");
        return Map.of("deleted",true,"assetId",id,"objectDeleted",true);
    }

    public List<Map<String,Object>> reviews(String actor,String status,int limit){
        authorize(actor);
        String sql="SELECT * FROM moderation_reviews";List<Object> args=new ArrayList<>();
        if(status!=null&&!status.isBlank()){sql+=" WHERE status=?";args.add(status);}
        sql+=" ORDER BY created_at DESC LIMIT ?";args.add(limit(limit));
        return jdbc.query(sql,(rs,n)->{
            Map<String,Object> m=new LinkedHashMap<>();
            m.put("id",rs.getString("id"));m.put("targetType",rs.getString("target_type"));m.put("targetId",rs.getString("target_id"));
            m.put("status",rs.getString("status"));m.put("reason",rs.getString("reason"));m.put("reviewerId",rs.getString("reviewer_id"));
            m.put("createdAt",rs.getTimestamp("created_at"));m.put("reviewedAt",rs.getTimestamp("reviewed_at"));return m;
        },args.toArray());
    }

    /** Per-job AgentScope usage rollup so maintainers can see the billing failure window. */
    public List<Map<String,Object>> agentUsage(String actor,String jobId,int limit){
        authorize(actor);
        String sql="""
            SELECT c.job_id,j.status AS job_status,j.engine,c.model,
                   SUM(c.state='completed') AS completed_calls,
                   SUM(c.state='pending') AS pending_calls,
                   SUM(c.state='unknown') AS unknown_calls,
                   COALESCE(SUM(CASE WHEN c.state='completed' THEN c.prompt_tokens+c.completion_tokens END),0) AS recorded_tokens
            FROM agent_model_calls c JOIN create_jobs j ON j.id=c.job_id
            WHERE j.deleted_at IS NULL
            """;
        List<Object> args=new ArrayList<>();
        if(jobId!=null&&!jobId.isBlank()){sql+=" AND c.job_id=?";args.add(jobId);}
        sql+=" GROUP BY c.job_id,j.status,j.engine,c.model ORDER BY unknown_calls DESC,completed_calls DESC LIMIT ?";args.add(limit(limit));
        return jdbc.query(sql,(rs,n)->{
            Map<String,Object> m=new LinkedHashMap<>();
            m.put("jobId",rs.getString("job_id"));m.put("jobStatus",rs.getString("job_status"));
            m.put("engine",rs.getString("engine"));m.put("model",rs.getString("model"));
            m.put("completedCalls",rs.getLong("completed_calls"));m.put("pendingCalls",rs.getLong("pending_calls"));
            m.put("unknownCalls",rs.getLong("unknown_calls"));m.put("recordedTokens",rs.getLong("recorded_tokens"));
            return m;
        },args.toArray());
    }

    private Map<String,Object> review(String actor,String type,String target,String status,String reason){
        String id=UUID.randomUUID().toString();
        jdbc.update("INSERT INTO moderation_reviews(id,target_type,target_id,status,reason,reviewer_id,reviewed_at) VALUES (?,?,?,?,?,?,UTC_TIMESTAMP())",
                id,type,target,status,sanitize(reason,1000),actor);
        audit(actor,"maintenance."+type+".reviewed",type,target,"{}");
        var row=jdbc.queryForMap("SELECT * FROM moderation_reviews WHERE id=?",id);
        Map<String,Object> result=new LinkedHashMap<>();
        result.put("id",row.get("id"));result.put("targetType",row.get("target_type"));result.put("targetId",row.get("target_id"));
        result.put("status",row.get("status"));result.put("reason",row.get("reason"));result.put("reviewerId",row.get("reviewer_id"));
        result.put("createdAt",row.get("created_at"));result.put("reviewedAt",row.get("reviewed_at"));
        return result;
    }

    private void audit(String actor,String action,String type,String id,String metadata){
        jdbc.update("INSERT INTO audit_logs(id,actor_user_id,action,target_type,target_id,metadata) VALUES (?,?,?,?,?,?)",
                UUID.randomUUID().toString(),actor,action,type,id,metadata);
    }

    private Map<String,Object> oneGame(String id){
        var rows=jdbc.queryForList("SELECT * FROM games WHERE id=? AND publish_status<>'deleted'",id);
        if(rows.isEmpty())throw new ResponseStatusException(HttpStatus.NOT_FOUND,"Game not found");
        var r=rows.get(0);
        return game(id,r.get("slug").toString(),r.get("title").toString(),(String)r.get("description"),
                r.get("visibility").toString(),r.get("publish_status").toString(),((Number)r.get("plays_count")).longValue(),
                ((Number)r.get("likes_count")).longValue(),((Number)r.get("favorites_count")).longValue(),
                r.get("author_id").toString(),r.get("updated_at"));
    }
    private Map<String,Object> game(String id,String slug,String title,String description,String visibility,String status,long plays,long likes,long favorites,String author,Object updated){
        Map<String,Object> m=new LinkedHashMap<>();
        m.put("id",id);m.put("slug",slug);m.put("title",title);m.put("description",description);m.put("visibility",visibility);
        m.put("publishStatus",status);m.put("plays",plays);m.put("likes",likes);m.put("favorites",favorites);
        m.put("coverAssetId",null);m.put("authorId",author);m.put("updatedAt",updated);return m;
    }
    private void authorize(String actor){
        var roles=jdbc.queryForList("SELECT role FROM users WHERE id=?",String.class,actor);
        if(roles.isEmpty()||!Set.of("admin","maintainer").contains(roles.get(0).toLowerCase()))
            throw new ResponseStatusException(HttpStatus.FORBIDDEN,"Maintainer role required");
    }
    private long count(String sql,Object...args){Long n=jdbc.queryForObject(sql,Long.class,args);return n==null?0:n;}
    private int limit(int n){return Math.max(1,Math.min(100,n));}
    private String sanitize(String text,int max){
        if(text==null)return "";
        String s=text.replaceAll("(?i)authorization\\s*:\\s*(?:Bearer|Basic)\\s+[^\\s,;]+","[redacted]")
                .replaceAll("(?i)(api[_-]?key|token|secret|password|authorization)\\s*[:=]\\s*[^\\s,;]+","[redacted]");
        return s.length()>max?s.substring(0,max)+"...":s;
    }
}
