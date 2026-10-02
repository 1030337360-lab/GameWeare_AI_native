package com.gameweare.api.catalog.dao;

import com.gameweare.api.catalog.entity.GameCommentEntity;
import java.util.List;
import java.util.Map;
import org.apache.ibatis.annotations.Arg;
import org.apache.ibatis.annotations.ConstructorArgs;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

@Mapper
public interface GameCommentMapper {
    @Select("SELECT id,comments_count FROM games WHERE slug=#{slug} "
            + "AND publish_status='published' AND visibility='public'")
    Map<String, Object> findPublicGame(@Param("slug") String slug);

    @ConstructorArgs({
            @Arg(column = "id", javaType = String.class),
            @Arg(column = "user_id", javaType = String.class),
            @Arg(column = "content", javaType = String.class),
            @Arg(column = "created_at", javaType = java.sql.Timestamp.class),
            @Arg(column = "display_name", javaType = String.class)
    })
    @Select("SELECT c.id,c.user_id,c.content,c.created_at,u.display_name "
            + "FROM game_comments c JOIN users u ON u.id=c.user_id "
            + "WHERE c.game_id=#{gameId} AND c.deleted_at IS NULL "
            + "ORDER BY c.created_at DESC,c.id DESC LIMIT #{limit} OFFSET #{offset}")
    List<GameCommentEntity> list(@Param("gameId") String gameId,
                                 @Param("limit") int limit, @Param("offset") int offset);

    @Insert("INSERT INTO game_comments(id,game_id,user_id,content) "
            + "VALUES(#{id},#{gameId},#{userId},#{content})")
    int insert(@Param("id") String id, @Param("gameId") String gameId,
               @Param("userId") String userId, @Param("content") String content);

    @Update("UPDATE games SET comments_count=comments_count+1 WHERE id=#{gameId}")
    int incrementCount(@Param("gameId") String gameId);

    @ConstructorArgs({
            @Arg(column = "id", javaType = String.class),
            @Arg(column = "user_id", javaType = String.class),
            @Arg(column = "content", javaType = String.class),
            @Arg(column = "created_at", javaType = java.sql.Timestamp.class),
            @Arg(column = "display_name", javaType = String.class)
    })
    @Select("SELECT c.id,c.user_id,c.content,c.created_at,u.display_name "
            + "FROM game_comments c JOIN users u ON u.id=c.user_id WHERE c.id=#{id}")
    GameCommentEntity findById(@Param("id") String id);

    @Update("UPDATE game_comments SET deleted_at=NOW(6) "
            + "WHERE id=#{id} AND game_id=#{gameId} AND user_id=#{userId} AND deleted_at IS NULL")
    int softDelete(@Param("id") String id, @Param("gameId") String gameId, @Param("userId") String userId);

    @Update("UPDATE games SET comments_count=GREATEST(comments_count-1,0) WHERE id=#{gameId}")
    int decrementCount(@Param("gameId") String gameId);
}
