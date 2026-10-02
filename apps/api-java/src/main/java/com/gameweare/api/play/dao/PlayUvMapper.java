package com.gameweare.api.play.dao;

import com.gameweare.api.play.entity.PlayIdentityEvent;
import java.sql.Date;
import java.util.List;
import org.apache.ibatis.annotations.Arg;
import org.apache.ibatis.annotations.ConstructorArgs;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

@Mapper
public interface PlayUvMapper {
    @Select({"<script>",
            "SELECT COUNT(DISTINCT COALESCE(CONCAT('u:',user_id),CONCAT('a:',anonymous_id)))",
            "FROM play_events WHERE created_at &gt;= #{from} AND created_at &lt; #{until}",
            "AND event_type IN ('game_view','game_start')",
            "<if test='gameId != null'>AND game_id=#{gameId}</if>",
            "</script>"})
    Long exactUv(@Param("from") Date from, @Param("until") Date until, @Param("gameId") String gameId);

    @ConstructorArgs({
            @Arg(column = "game_id", javaType = String.class),
            @Arg(column = "user_id", javaType = String.class),
            @Arg(column = "anonymous_id", javaType = String.class),
            @Arg(column = "created_at", javaType = java.sql.Timestamp.class)
    })
    @Select("SELECT game_id,user_id,anonymous_id,created_at FROM play_events "
            + "WHERE created_at>=#{from} AND event_type IN ('game_view','game_start') "
            + "ORDER BY created_at DESC LIMIT 100000")
    List<PlayIdentityEvent> recentEvents(@Param("from") Date from);
}
