package com.gameweare.api.catalog.dao;

import java.util.List;
import java.util.Map;
import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

/** Catalog SQL is explicit, including each allowed interaction table and counter column. */
@Mapper
public interface CatalogMapper {
    @Select({"<script>",
            "SELECT g.id,g.slug,g.title,g.description,g.author_id,g.cover_object_key,",
            "g.plays_count,g.likes_count,g.favorites_count,g.comments_count,g.published_at,g.created_at,",
            "u.display_name AS author,",
            "(SELECT GROUP_CONCAT(t.name SEPARATOR '|||') FROM game_tags gt JOIN tags t ON t.id=gt.tag_id WHERE gt.game_id=g.id) AS tag_names,",
            "EXISTS(SELECT 1 FROM game_likes l WHERE l.game_id=g.id AND l.user_id=#{userId}) AS liked,",
            "EXISTS(SELECT 1 FROM game_favorites f WHERE f.game_id=g.id AND f.user_id=#{userId}) AS favorited",
            "FROM games g LEFT JOIN users u ON u.id=g.author_id",
            "WHERE g.publish_status='published' AND g.visibility='public'",
            "<if test='search != null'>",
            "AND (g.title LIKE #{search} OR g.description LIKE #{search} OR EXISTS",
            "(SELECT 1 FROM game_tags qgt JOIN tags qt ON qt.id=qgt.tag_id",
            "WHERE qgt.game_id=g.id AND qt.name LIKE #{search}))",
            "</if>",
            "<if test='tag != null'>",
            "AND EXISTS (SELECT 1 FROM game_tags gt JOIN tags t ON t.id=gt.tag_id",
            "WHERE gt.game_id=g.id AND LOWER(t.name)=LOWER(#{tag}))",
            "</if>",
            "<choose>",
            "<when test='sort == \"likes\"'>ORDER BY g.likes_count DESC,g.published_at DESC,g.id DESC</when>",
            "<otherwise>ORDER BY g.published_at DESC,g.created_at DESC,g.id DESC</otherwise>",
            "</choose>",
            "LIMIT 100",
            "</script>"})
    List<Map<String, Object>> list(@Param("userId") String userId, @Param("search") String search,
                                   @Param("tag") String tag, @Param("sort") String sort);

    @Select("SELECT DISTINCT t.name FROM tags t JOIN game_tags gt ON gt.tag_id=t.id "
            + "JOIN games g ON g.id=gt.game_id WHERE g.publish_status='published' "
            + "AND g.visibility='public' ORDER BY t.name")
    List<String> tags();

    @Select("SELECT COUNT(*) FROM games WHERE slug=#{slug} AND publish_status='published' AND visibility='public'")
    int publicCount(@Param("slug") String slug);

    @Select("SELECT EXISTS(SELECT 1 FROM game_likes l WHERE l.game_id=g.id AND l.user_id=#{userId}) AS liked,"
            + "EXISTS(SELECT 1 FROM game_favorites f WHERE f.game_id=g.id AND f.user_id=#{userId}) AS favorited "
            + "FROM games g WHERE g.slug=#{slug}")
    Map<String, Object> interactionFlags(@Param("userId") String userId, @Param("slug") String slug);

    @Select("SELECT g.id,g.slug,g.title,g.description,g.author_id,g.cover_object_key,"
            + "g.plays_count,g.likes_count,g.favorites_count,g.comments_count,g.published_at,g.created_at,"
            + "u.display_name AS author,"
            + "(SELECT GROUP_CONCAT(t.name SEPARATOR '|||') FROM game_tags gt JOIN tags t ON t.id=gt.tag_id WHERE gt.game_id=g.id) AS tag_names,"
            + "EXISTS(SELECT 1 FROM game_likes l WHERE l.game_id=g.id AND l.user_id='') AS liked,"
            + "EXISTS(SELECT 1 FROM game_favorites f WHERE f.game_id=g.id AND f.user_id='') AS favorited "
            + "FROM games g LEFT JOIN users u ON u.id=g.author_id "
            + "WHERE g.slug=#{slug} AND g.publish_status='published' AND g.visibility='public' LIMIT 1")
    Map<String, Object> publicDetail(@Param("slug") String slug);

    @Select("SELECT v.id,v.version_no,v.runtime,v.build_status,v.safety_status,v.entry_file,"
            + "v.storage_prefix,v.manifest_object_key,v.source_job_id,v.created_at,"
            + "(g.current_version_id=v.id) AS current_version "
            + "FROM games g JOIN game_versions v ON v.game_id=g.id "
            + "WHERE g.slug=#{slug} AND g.publish_status='published' AND g.visibility='public' "
            + "ORDER BY v.version_no DESC")
    List<Map<String, Object>> versions(@Param("slug") String slug);

    @Update("UPDATE games g JOIN game_versions v ON v.game_id=g.id SET g.current_version_id=v.id "
            + "WHERE g.slug=#{slug} AND g.author_id=#{userId} AND v.id=#{versionId} "
            + "AND v.build_status='passed' AND v.safety_status='passed'")
    int switchVersion(@Param("slug") String slug, @Param("versionId") String versionId,
                      @Param("userId") String userId);

    @Select("SELECT id FROM games WHERE slug=#{slug} AND author_id=#{userId} AND publish_status<>'deleted'")
    String ownedGameId(@Param("slug") String slug, @Param("userId") String userId);

    @Update("UPDATE games SET publish_status='deleted',visibility='private' WHERE id=#{gameId}")
    int softDelete(@Param("gameId") String gameId);

    @Select("SELECT title,description,cover_object_key FROM games "
            + "WHERE slug=#{slug} AND publish_status='published' AND visibility='public' LIMIT 1")
    Map<String, Object> remixSource(@Param("slug") String slug);

    @Insert("INSERT INTO games(id,slug,title,description,author_id,publish_status,visibility,cover_object_key) "
            + "VALUES(#{id},#{slug},#{title},#{description},#{authorId},'draft','private',#{coverKey})")
    int insertRemix(@Param("id") String id, @Param("slug") String slug, @Param("title") String title,
                    @Param("description") String description, @Param("authorId") String authorId,
                    @Param("coverKey") String coverKey);

    @Insert("INSERT INTO create_projects(id,user_id,title,status,game_id) "
            + "VALUES(#{id},#{userId},#{title},'active',#{gameId})")
    int insertRemixProject(@Param("id") String id, @Param("userId") String userId,
                           @Param("title") String title, @Param("gameId") String gameId);

    @Select("SELECT id FROM games WHERE slug=#{slug} AND publish_status='published' AND visibility='public'")
    String publicGameId(@Param("slug") String slug);

    @Insert("INSERT IGNORE INTO game_likes(user_id,game_id) VALUES(#{userId},#{gameId})")
    int like(@Param("userId") String userId, @Param("gameId") String gameId);

    @Delete("DELETE FROM game_likes WHERE user_id=#{userId} AND game_id=#{gameId}")
    int unlike(@Param("userId") String userId, @Param("gameId") String gameId);

    @Insert("INSERT IGNORE INTO game_favorites(user_id,game_id) VALUES(#{userId},#{gameId})")
    int favorite(@Param("userId") String userId, @Param("gameId") String gameId);

    @Delete("DELETE FROM game_favorites WHERE user_id=#{userId} AND game_id=#{gameId}")
    int unfavorite(@Param("userId") String userId, @Param("gameId") String gameId);

    @Update("UPDATE games SET likes_count=likes_count+1 WHERE id=#{gameId}")
    int incrementLikes(@Param("gameId") String gameId);

    @Update("UPDATE games SET likes_count=GREATEST(likes_count-1,0) WHERE id=#{gameId}")
    int decrementLikes(@Param("gameId") String gameId);

    @Update("UPDATE games SET favorites_count=favorites_count+1 WHERE id=#{gameId}")
    int incrementFavorites(@Param("gameId") String gameId);

    @Update("UPDATE games SET favorites_count=GREATEST(favorites_count-1,0) WHERE id=#{gameId}")
    int decrementFavorites(@Param("gameId") String gameId);

    @Select("SELECT g.likes_count,g.favorites_count,"
            + "EXISTS(SELECT 1 FROM game_likes l WHERE l.game_id=g.id AND l.user_id=#{userId}) AS liked,"
            + "EXISTS(SELECT 1 FROM game_favorites f WHERE f.game_id=g.id AND f.user_id=#{userId}) AS favorited "
            + "FROM games g WHERE g.id=#{gameId}")
    Map<String, Object> interactionSummary(@Param("userId") String userId, @Param("gameId") String gameId);
}
