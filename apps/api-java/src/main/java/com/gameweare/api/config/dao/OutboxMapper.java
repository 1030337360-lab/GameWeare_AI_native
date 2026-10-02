package com.gameweare.api.config.dao;

import java.util.List;
import java.util.Map;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

/** Conditional claim prevents two publishers from sending the same pending row concurrently. */
@Mapper
public interface OutboxMapper {
    @Select("SELECT id,aggregate_id FROM outbox_events "
            + "WHERE status='pending' AND available_at<=CURRENT_TIMESTAMP(6) "
            + "ORDER BY created_at LIMIT 100")
    List<Map<String, Object>> pending();

    @Update("UPDATE outbox_events SET status='sending',sending_at=CURRENT_TIMESTAMP(6),attempts=attempts+1 "
            + "WHERE id=#{id} AND status='pending'")
    int claim(@Param("id") String id);

    @Update("UPDATE outbox_events SET status='sent',sent_at=CURRENT_TIMESTAMP(6) WHERE id=#{id}")
    int markSent(@Param("id") String id);

    @Update("UPDATE outbox_events SET status='pending',sending_at=NULL,"
            + "available_at=DATE_ADD(CURRENT_TIMESTAMP(6), "
            + "INTERVAL LEAST(POW(2, LEAST(attempts, 8)), 300) SECOND) WHERE id=#{id}")
    int retryLater(@Param("id") String id);

    @Update("UPDATE outbox_events SET status='pending',sending_at=NULL "
            + "WHERE status='sending' AND sending_at<DATE_SUB(CURRENT_TIMESTAMP(6), INTERVAL 5 MINUTE)")
    int recoverStale();
}
