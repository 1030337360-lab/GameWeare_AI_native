package com.gameweare.api.profile.dao;

import java.util.List;
import java.util.Map;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

@Mapper
public interface ProfileMapper {
    @Select("SELECT pe.id AS event_id,pe.event_type,pe.created_at,g.id AS game_id,g.slug,g.title,g.description,"
            + "g.cover_object_key,g.plays_count,g.likes_count,g.favorites_count,g.published_at,"
            + "u.display_name AS author FROM play_events pe JOIN games g ON g.id=pe.game_id "
            + "JOIN users u ON u.id=g.author_id WHERE pe.user_id=#{userId} "
            + "AND g.publish_status='published' AND g.visibility='public' "
            + "AND pe.id=(SELECT pe2.id FROM play_events pe2 "
            + "WHERE pe2.game_id=pe.game_id AND pe2.user_id=#{userId} "
            + "ORDER BY pe2.created_at DESC LIMIT 1) ORDER BY pe.created_at DESC LIMIT 3")
    List<Map<String, Object>> recentPlays(@Param("userId") String userId);

    @Select("SELECT p.id AS project_id,p.title,p.status,p.game_id,g.slug AS game_slug,p.updated_at,"
            + "(SELECT j.id FROM create_jobs j WHERE j.project_id=p.id ORDER BY j.created_at DESC LIMIT 1) AS latest_run_id,"
            + "(SELECT j.status FROM create_jobs j WHERE j.project_id=p.id ORDER BY j.created_at DESC LIMIT 1) AS latest_run_status "
            + "FROM create_projects p LEFT JOIN games g ON g.id=p.game_id "
            + "WHERE p.id=#{projectId} AND p.user_id=#{userId} AND p.status<>'deleted' LIMIT 1")
    Map<String, Object> project(@Param("projectId") String projectId, @Param("userId") String userId);

    @Select("SELECT id,prompt,status,create_type,agent_mode,created_at,updated_at "
            + "FROM create_jobs WHERE project_id=#{projectId} AND user_id=#{userId} ORDER BY created_at DESC")
    List<Map<String, Object>> projectRuns(@Param("projectId") String projectId,
                                          @Param("userId") String userId);

    @Select("SELECT step_no,stage,status,message,created_at FROM create_run_steps "
            + "WHERE job_id=#{jobId} ORDER BY step_no")
    List<Map<String, Object>> runSteps(@Param("jobId") String jobId);

    @Select("SELECT g.id AS game_id,g.slug,g.title,g.description,g.cover_object_key,"
            + "g.plays_count,g.likes_count,g.favorites_count,g.published_at,u.display_name AS author "
            + "FROM games g JOIN users u ON u.id=g.author_id "
            + "WHERE g.id=#{gameId} AND g.publish_status='published' AND g.visibility='public'")
    Map<String, Object> publicGame(@Param("gameId") String gameId);

    @Select("SELECT p.id AS project_id,p.title,p.status,p.game_id,g.slug AS game_slug,p.updated_at,"
            + "(SELECT j.id FROM create_jobs j WHERE j.project_id=p.id ORDER BY j.created_at DESC LIMIT 1) AS latest_run_id,"
            + "(SELECT j.status FROM create_jobs j WHERE j.project_id=p.id ORDER BY j.created_at DESC LIMIT 1) AS latest_run_status "
            + "FROM create_projects p LEFT JOIN games g ON g.id=p.game_id "
            + "WHERE p.user_id=#{userId} AND p.status<>'deleted' ORDER BY p.updated_at DESC LIMIT 100")
    List<Map<String, Object>> projects(@Param("userId") String userId);

    @Select("SELECT t.name FROM tags t JOIN game_tags gt ON gt.tag_id=t.id "
            + "WHERE gt.game_id=#{gameId} ORDER BY t.name")
    List<String> gameTags(@Param("gameId") String gameId);

    @Select("SELECT COUNT(*) FROM game_likes WHERE game_id=#{gameId} AND user_id=#{userId}")
    long likeCount(@Param("gameId") String gameId, @Param("userId") String userId);

    @Select("SELECT COUNT(*) FROM game_favorites WHERE game_id=#{gameId} AND user_id=#{userId}")
    long favoriteCount(@Param("gameId") String gameId, @Param("userId") String userId);
}
