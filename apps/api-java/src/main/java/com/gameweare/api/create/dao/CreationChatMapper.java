package com.gameweare.api.create.dao;

import java.util.List;
import java.util.Map;
import org.apache.ibatis.annotations.*;

@Mapper
public interface CreationChatMapper {
    @Insert("INSERT INTO create_chat_sessions(id,user_id,create_type,project_id,funding_mode,voucher_id) "
            + "VALUES(#{id},#{userId},#{type},#{projectId},#{funding},#{voucherId})")
    int insert(@Param("id") String id, @Param("userId") String userId, @Param("type") String type,
               @Param("projectId") String projectId, @Param("funding") String funding, @Param("voucherId") String voucherId);

    @Select("SELECT * FROM create_chat_sessions WHERE id=#{id} AND user_id=#{userId}")
    Map<String, Object> find(@Param("id") String id, @Param("userId") String userId);

    @Select("SELECT * FROM create_chat_sessions WHERE id=#{id} AND user_id=#{userId} FOR UPDATE")
    Map<String, Object> lock(@Param("id") String id, @Param("userId") String userId);

    @Select("SELECT * FROM create_chat_sessions WHERE user_id=#{userId} ORDER BY updated_at DESC LIMIT 30")
    List<Map<String, Object>> list(@Param("userId") String userId);

    @Select("SELECT request_id,role,content,skill_ids_json,prompt_tokens,completion_tokens,sequence_no,created_at "
            + "FROM create_chat_messages WHERE session_id=#{id} ORDER BY sequence_no")
    List<Map<String, Object>> messages(@Param("id") String id);

    @Select("SELECT COUNT(*) FROM create_chat_messages WHERE session_id=#{id} AND request_id=#{requestId} AND role='assistant'")
    int completedRequest(@Param("id") String id, @Param("requestId") String requestId);

    @Select("SELECT content FROM create_chat_messages WHERE session_id=#{id} AND request_id=#{requestId} AND role='user'")
    String requestMessage(@Param("id") String id, @Param("requestId") String requestId);

    @Update("UPDATE create_chat_sessions SET status='replying',pending_request_id=#{requestId},"
            + "reply_expires_at=DATE_ADD(UTC_TIMESTAMP(6),INTERVAL 5 MINUTE),updated_at=UTC_TIMESTAMP(6) "
            + "WHERE id=#{id} AND user_id=#{userId} AND revision=#{revision} "
            + "AND (status='draft' OR (status='replying' AND reply_expires_at<UTC_TIMESTAMP(6)))")
    int claim(@Param("id") String id, @Param("userId") String userId,
              @Param("requestId") String requestId, @Param("revision") int revision);

    @Update("UPDATE create_chat_sessions SET status='draft',revision=revision+1,brief_json=#{brief},"
            + "pending_request_id=NULL,reply_expires_at=NULL,updated_at=UTC_TIMESTAMP(6) "
            + "WHERE id=#{id} AND user_id=#{userId} AND revision=#{revision} AND status='replying' "
            + "AND pending_request_id=#{requestId} AND reply_expires_at>UTC_TIMESTAMP(6)")
    int finish(@Param("id") String id, @Param("userId") String userId, @Param("requestId") String requestId,
               @Param("revision") int revision, @Param("brief") String brief);

    @Update("UPDATE create_chat_sessions SET status='draft',pending_request_id=NULL,reply_expires_at=NULL "
            + "WHERE id=#{id} AND user_id=#{userId} AND status='replying' AND pending_request_id=#{requestId}")
    int release(@Param("id") String id, @Param("userId") String userId, @Param("requestId") String requestId);

    @Insert("INSERT INTO create_chat_messages(id,session_id,request_id,role,content,skill_ids_json,"
            + "sequence_no,prompt_tokens,completion_tokens) "
            + "VALUES(#{id},#{sessionId},#{requestId},#{role},#{content},#{skills},#{sequence},#{input},#{output})")
    int message(@Param("id") String id, @Param("sessionId") String sessionId, @Param("requestId") String requestId,
                @Param("role") String role, @Param("content") String content, @Param("skills") String skills,
                @Param("sequence") int sequence, @Param("input") long input, @Param("output") long output);

    @Update("UPDATE create_chat_sessions SET status='confirmed',job_id=#{jobId},updated_at=UTC_TIMESTAMP(6) "
            + "WHERE id=#{id} AND user_id=#{userId} AND status='draft' AND revision=#{revision}")
    int confirm(@Param("id") String id, @Param("userId") String userId,
                @Param("revision") int revision, @Param("jobId") String jobId);

    @Select("SELECT COUNT(*) FROM create_projects WHERE id=#{id} AND user_id=#{userId} "
            + "AND game_id IS NOT NULL AND status<>'archived'")
    int ownedProject(@Param("id") String id, @Param("userId") String userId);

    @Select("SELECT COUNT(*) FROM generation_vouchers WHERE id=#{id} AND user_id=#{userId} "
            + "AND status='available' AND expires_at>UTC_TIMESTAMP(6)")
    int availableVoucher(@Param("id") String id, @Param("userId") String userId);
}
