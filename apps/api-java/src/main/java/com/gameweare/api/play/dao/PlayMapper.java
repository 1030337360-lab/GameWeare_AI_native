package com.gameweare.api.play.dao;

import java.sql.Timestamp;
import java.util.Map;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

@Mapper
public interface PlayMapper {
    @Select("SELECT id FROM games WHERE slug=#{slug} AND publish_status='published' AND visibility='public'")
    String publicGameId(@Param("slug") String slug);

    // Former JDBC INSERT IGNORE is deliberately preserved: the unique key decides the first play in a window.
    @Insert("INSERT IGNORE INTO play_count_dedupe(game_id,identity_key,window_start) "
            + "VALUES(#{gameId},#{identity},#{windowStart})")
    int countOnce(@Param("gameId") String gameId, @Param("identity") String identity,
                  @Param("windowStart") Timestamp windowStart);

    @Insert("INSERT INTO play_events(id,user_id,anonymous_id,game_id,event_type,created_at) "
            + "VALUES(#{id},#{userId},#{anonymousId},#{gameId},#{eventType},UTC_TIMESTAMP())")
    int insertEvent(@Param("id") String id, @Param("userId") String userId,
                    @Param("anonymousId") String anonymousId, @Param("gameId") String gameId,
                    @Param("eventType") String eventType);

    @Update("UPDATE games SET plays_count=plays_count+1 WHERE id=#{gameId}")
    int incrementPlays(@Param("gameId") String gameId);

    @Select("SELECT g.title,v.version_no,v.runtime,v.entry_file,v.entry_object_key "
            + "FROM games g JOIN game_versions v ON v.id=g.current_version_id "
            + "WHERE g.slug=#{slug} AND g.publish_status='published' AND g.visibility='public' LIMIT 1")
    Map<String, Object> publishedVersion(@Param("slug") String slug);
}
