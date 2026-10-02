package com.gameweare.api.voucher.dao;

import java.util.List;
import java.util.Map;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

/** Conditional updates are the voucher state machine's concurrency boundary. */
@Mapper
public interface GenerationVoucherMapper {
    @Select("SELECT id,source_type AS sourceType,source_id AS sourceId,status,expires_at AS expiresAt,"
            + "reserved_job_id AS reservedJobId,created_at AS createdAt,used_at AS usedAt "
            + "FROM generation_vouchers WHERE user_id=#{userId} ORDER BY created_at DESC LIMIT 100")
    List<Map<String, Object>> mine(@Param("userId") String userId);

    @Insert("INSERT IGNORE INTO generation_vouchers(id,user_id,source_type,source_id,status,expires_at) "
            + "VALUES(#{id},#{userId},#{sourceType},#{sourceId},'available',"
            + "DATE_ADD(UTC_TIMESTAMP(6), INTERVAL #{validityDays} DAY))")
    int grant(@Param("id") String id, @Param("userId") String userId,
              @Param("sourceType") String sourceType, @Param("sourceId") String sourceId,
              @Param("validityDays") int validityDays);

    @Update("UPDATE generation_vouchers SET status='reserved',reserved_job_id=#{jobId} "
            + "WHERE id=#{voucherId} AND user_id=#{userId} AND status='available' "
            + "AND expires_at>UTC_TIMESTAMP(6)")
    int reserve(@Param("userId") String userId, @Param("voucherId") String voucherId,
                @Param("jobId") String jobId);

    @Update("UPDATE generation_vouchers SET status='used',used_at=UTC_TIMESTAMP(6) "
            + "WHERE user_id=#{userId} AND reserved_job_id=#{jobId} AND status='reserved'")
    int consume(@Param("userId") String userId, @Param("jobId") String jobId);

    @Update("UPDATE generation_vouchers SET status=IF(expires_at>UTC_TIMESTAMP(6),'available','expired'),"
            + "reserved_job_id=NULL WHERE user_id=#{userId} AND reserved_job_id=#{jobId} AND status='reserved'")
    int release(@Param("userId") String userId, @Param("jobId") String jobId);

    @Update("UPDATE generation_vouchers SET status='expired' "
            + "WHERE status='available' AND expires_at<=UTC_TIMESTAMP(6)")
    int expireUnreserved();

    @Select("SELECT v.user_id,v.reserved_job_id,j.status "
            + "FROM generation_vouchers v JOIN create_jobs j ON j.id=v.reserved_job_id "
            + "WHERE v.status='reserved' AND j.status IN ('completed','failed','canceled') LIMIT 100")
    List<Map<String, Object>> terminalReservations();
}
