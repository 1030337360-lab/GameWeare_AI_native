package com.gameweare.api.catalog.dao;

import java.util.List;
import java.util.Map;
import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

@Mapper
public interface CreatorCommunityMapper {
    @Select("SELECT u.id,u.display_name AS displayName,u.avatar_url AS avatarUrl,"
            + "(SELECT COUNT(*) FROM creator_follows f WHERE f.creator_id=u.id) AS followers "
            + "FROM users u WHERE u.id=#{id} AND EXISTS("
            + "SELECT 1 FROM games g WHERE g.author_id=u.id AND g.publish_status='published' AND g.visibility='public')")
    Map<String, Object> profile(@Param("id") String id);

    @Select("SELECT COUNT(*) FROM creator_follows WHERE user_id=#{userId} AND creator_id=#{creatorId}")
    int followCount(@Param("userId") String userId, @Param("creatorId") String creatorId);

    @Insert("INSERT IGNORE INTO creator_follows(user_id,creator_id) VALUES(#{userId},#{creatorId})")
    int follow(@Param("userId") String userId, @Param("creatorId") String creatorId);

    @Delete("DELETE FROM creator_follows WHERE user_id=#{userId} AND creator_id=#{creatorId}")
    int unfollow(@Param("userId") String userId, @Param("creatorId") String creatorId);

    @Select("SELECT id,display_name AS displayName,avatar_url AS avatarUrl FROM users u WHERE u.id=#{id} "
            + "AND EXISTS (SELECT 1 FROM games g WHERE g.author_id=u.id "
            + "AND g.publish_status='published' AND g.visibility='public')")
    Map<String, Object> publicCreator(@Param("id") String id);

    @Select("SELECT u.id,u.display_name AS displayName,u.avatar_url AS avatarUrl "
            + "FROM creator_follows a JOIN creator_follows b ON b.creator_id=a.creator_id "
            + "JOIN users u ON u.id=a.creator_id "
            + "WHERE a.user_id=#{userId} AND b.user_id=#{otherId} AND EXISTS "
            + "(SELECT 1 FROM games g WHERE g.author_id=u.id AND g.publish_status='published' "
            + "AND g.visibility='public') LIMIT 50")
    List<Map<String, Object>> common(@Param("userId") String userId, @Param("otherId") String otherId);

    @Select("SELECT g.slug AS id,g.title,g.description,g.published_at AS publishedAt,"
            + "u.id AS creatorId,u.display_name AS creatorName,g.plays_count AS plays,"
            + "g.likes_count AS likes FROM creator_follows f JOIN games g ON g.author_id=f.creator_id "
            + "JOIN users u ON u.id=f.creator_id "
            + "WHERE f.user_id=#{userId} AND g.publish_status='published' AND g.visibility='public' "
            + "ORDER BY g.published_at DESC,g.id DESC LIMIT #{limit}")
    List<Map<String, Object>> feed(@Param("userId") String userId, @Param("limit") int limit);

    @Select("SELECT creator_id FROM creator_follows WHERE user_id=#{userId}")
    List<String> followingIds(@Param("userId") String userId);
}
