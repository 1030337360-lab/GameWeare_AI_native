package com.gameweare.api.catalog.dao;

import java.util.List;
import java.util.Map;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

/** Published-game projection queries used to rebuild Redis views. */
@Mapper
public interface GameStatsMapper {
    @Select("SELECT slug FROM games WHERE publish_status='published' AND visibility='public'")
    List<String> publicSlugs();

    @Select("SELECT plays_count,likes_count,favorites_count,publish_status,visibility FROM games WHERE id=#{gameId}")
    Map<String, Object> counters(@Param("gameId") String gameId);

    @Select("SELECT g.slug AS id,g.title,u.display_name AS author,"
            + "g.plays_count AS plays,g.likes_count AS likes,g.favorites_count AS favorites "
            + "FROM games g JOIN users u ON u.id=g.author_id "
            + "WHERE g.publish_status='published' AND g.visibility='public' "
            + "ORDER BY (g.plays_count+3*g.likes_count+5*g.favorites_count) DESC,g.published_at DESC "
            + "LIMIT #{limit}")
    List<Map<String, Object>> topGames(@Param("limit") int limit);

    @Select("SELECT g.slug AS id,g.title,u.display_name AS author,"
            + "g.plays_count AS plays,g.likes_count AS likes,g.favorites_count AS favorites "
            + "FROM games g JOIN users u ON u.id=g.author_id "
            + "WHERE g.id=#{gameId} AND g.publish_status='published' AND g.visibility='public'")
    Map<String, Object> publicGameSummary(@Param("gameId") String gameId);

    @Select("SELECT id,plays_count,likes_count,favorites_count FROM games "
            + "WHERE publish_status='published' AND visibility='public' "
            + "ORDER BY (plays_count+3*likes_count+5*favorites_count) DESC LIMIT 1000")
    List<Map<String, Object>> topCounters();
}
