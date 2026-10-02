package com.gameweare.api.create.dao;

import java.util.Map;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

/** Persistence for externally supplied, locally validated game artifacts. */
@Mapper
public interface ArtifactMapper {
    @Select("SELECT id FROM users WHERE id=#{userId} FOR UPDATE")
    String lockUser(@Param("userId") String userId);

    @Select("SELECT id,project_id,game_id,version_id,prompt,artifact_sha256 "
            + "FROM create_jobs WHERE user_id=#{userId} AND idempotency_key=#{key}")
    Map<String, Object> existingJob(@Param("userId") String userId, @Param("key") String key);

    @Insert("INSERT INTO create_projects(id,user_id,title,status,created_at,updated_at) "
            + "VALUES(#{id},#{userId},#{title},'draft',NOW(),NOW())")
    int insertProject(@Param("id") String id, @Param("userId") String userId, @Param("title") String title);

    @Select("SELECT game_id,status FROM create_projects "
            + "WHERE id=#{projectId} AND user_id=#{userId} FOR UPDATE")
    Map<String, Object> lockProject(@Param("projectId") String projectId, @Param("userId") String userId);

    @Select("SELECT COUNT(*) FROM create_jobs WHERE project_id=#{projectId} "
            + "AND status IN ('pending','generating','planning','reviewing')")
    int activeJobCount(@Param("projectId") String projectId);

    @Select("SELECT id FROM games WHERE id=#{gameId} AND author_id=#{userId} FOR UPDATE")
    String ownedGameId(@Param("gameId") String gameId, @Param("userId") String userId);

    @Insert("INSERT INTO games(id,slug,title,description,author_id,publish_status,visibility,created_at,updated_at) "
            + "VALUES(#{id},#{slug},#{title},#{title},#{userId},'draft','private',NOW(),NOW())")
    int insertGame(@Param("id") String id, @Param("slug") String slug,
                   @Param("title") String title, @Param("userId") String userId);

    @Select("SELECT COALESCE(MAX(version_no),0)+1 FROM game_versions WHERE game_id=#{gameId}")
    int nextVersionNo(@Param("gameId") String gameId);

    @Insert("INSERT INTO create_jobs(id,user_id,project_id,prompt,agent_mode,create_type,status,"
            + "game_id,version_id,idempotency_key,artifact_sha256,reserved_tokens,actual_tokens,created_at,updated_at) "
            + "VALUES(#{id},#{userId},#{projectId},#{prompt},'external','init','completed',"
            + "#{gameId},#{versionId},#{key},#{digest},0,0,NOW(),NOW())")
    int insertJob(@Param("id") String id, @Param("userId") String userId,
                  @Param("projectId") String projectId, @Param("prompt") String prompt,
                  @Param("gameId") String gameId, @Param("versionId") String versionId,
                  @Param("key") String key, @Param("digest") String digest);

    @Insert("INSERT INTO game_versions(id,game_id,version_no,entry_object_key,runtime,"
            + "build_status,safety_status,entry_file,storage_prefix,source_job_id) "
            + "VALUES(#{id},#{gameId},#{versionNo},#{objectKey},'iframe-html5','passed','pending',"
            + "'index.html',#{prefix},#{jobId})")
    int insertVersion(@Param("id") String id, @Param("gameId") String gameId,
                      @Param("versionNo") int versionNo, @Param("objectKey") String objectKey,
                      @Param("prefix") String prefix, @Param("jobId") String jobId);

    @Insert("INSERT INTO assets(id,owner_id,game_id,version_id,job_id,kind,bucket,"
            + "object_key,content_type,size_bytes) "
            + "VALUES(#{id},#{userId},#{gameId},#{versionId},#{jobId},'html',"
            + "#{bucket},#{objectKey},#{contentType},#{sizeBytes})")
    int insertAsset(@Param("id") String id, @Param("userId") String userId,
                    @Param("gameId") String gameId, @Param("versionId") String versionId,
                    @Param("jobId") String jobId, @Param("bucket") String bucket,
                    @Param("objectKey") String objectKey, @Param("contentType") String contentType,
                    @Param("sizeBytes") long sizeBytes);

    @Update("UPDATE games SET current_version_id=#{versionId},updated_at=NOW() WHERE id=#{gameId}")
    int setCurrentVersion(@Param("versionId") String versionId, @Param("gameId") String gameId);

    @Update("UPDATE create_projects SET game_id=#{gameId},status='completed',updated_at=NOW() "
            + "WHERE id=#{projectId}")
    int completeProject(@Param("gameId") String gameId, @Param("projectId") String projectId);

    @Insert("INSERT INTO create_run_steps(id,job_id,step_no,stage,status,message) "
            + "VALUES(#{id},#{jobId},1,'compile','completed','Artifact syntax validated')")
    int insertCompileStep(@Param("id") String id, @Param("jobId") String jobId);
}
