package com.gameweare.api.voucher.dao;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

/** Redis admits provisional reservations; these MySQL statements decide final issuance. */
@Mapper
public interface VoucherCampaignMapper {
    @Select("SELECT id,title,starts_at,ends_at,total_stock,remaining_stock,status "
            + "FROM voucher_campaigns WHERE status<>'canceled' ORDER BY starts_at DESC LIMIT 50")
    List<Map<String, Object>> list();

    @Insert("INSERT INTO voucher_campaigns(id,title,starts_at,ends_at,total_stock,remaining_stock) "
            + "VALUES(#{id},#{title},#{startsAt},#{endsAt},#{stock},#{stock})")
    int insertCampaign(@Param("id") String id, @Param("title") String title,
                       @Param("startsAt") LocalDateTime startsAt, @Param("endsAt") LocalDateTime endsAt,
                       @Param("stock") int stock);

    @Select("SELECT starts_at,ends_at,status FROM voucher_campaigns WHERE id=#{id}")
    Map<String, Object> campaign(@Param("id") String id);

    @Select("SELECT c.id AS reservationId,c.status,v.id AS voucherId "
            + "FROM voucher_claims c LEFT JOIN generation_vouchers v "
            + "ON v.user_id=c.user_id AND v.source_type='campaign' AND v.source_id=c.campaign_id "
            + "WHERE c.campaign_id=#{campaignId} AND c.user_id=#{userId} LIMIT 1")
    Map<String, Object> claimByUser(@Param("campaignId") String campaignId, @Param("userId") String userId);

    @Select("SELECT COUNT(*) FROM voucher_claims "
            + "WHERE id=#{reservationId} AND campaign_id=#{campaignId} AND user_id=#{userId}")
    int ownedReservationCount(@Param("reservationId") String reservationId,
                              @Param("campaignId") String campaignId, @Param("userId") String userId);

    // Former JDBC SELECT ... FOR UPDATE: serialize issuance and compensation by campaign.
    @Select("SELECT remaining_stock FROM voucher_campaigns WHERE id=#{campaignId} FOR UPDATE")
    Integer lockStock(@Param("campaignId") String campaignId);

    @Select("SELECT COUNT(*) FROM voucher_claims WHERE id=#{reservationId}")
    int claimCountById(@Param("reservationId") String reservationId);

    @Select("SELECT COUNT(*) FROM voucher_claims WHERE campaign_id=#{campaignId} AND user_id=#{userId}")
    int claimCountByUser(@Param("campaignId") String campaignId, @Param("userId") String userId);

    @Update("UPDATE voucher_campaigns SET remaining_stock=remaining_stock-1 "
            + "WHERE id=#{campaignId} AND remaining_stock>0 AND status<>'canceled'")
    int decrementStock(@Param("campaignId") String campaignId);

    @Insert("INSERT INTO voucher_claims(id,campaign_id,user_id,remaining_after,status) "
            + "VALUES(#{reservationId},#{campaignId},#{userId},#{remainingAfter},'issued')")
    int insertClaim(@Param("reservationId") String reservationId, @Param("campaignId") String campaignId,
                    @Param("userId") String userId, @Param("remainingAfter") int remainingAfter);

    @Select("SELECT total_stock AS totalStock,remaining_stock AS remainingStock,"
            + "(SELECT COUNT(*) FROM voucher_claims WHERE campaign_id=#{campaignId}) AS issuedCount "
            + "FROM voucher_campaigns WHERE id=#{campaignId}")
    Map<String, Object> reconcile(@Param("campaignId") String campaignId);

    @Select("SELECT id FROM voucher_campaigns "
            + "WHERE ends_at>DATE_SUB(UTC_TIMESTAMP(6), INTERVAL 45 DAY)")
    List<String> recentCampaignIds();
}
