package com.gameweare.api.voucher.dao;

import java.sql.Date;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

@Mapper
public interface CheckinMapper {
    @Insert("INSERT IGNORE INTO checkin_streaks(user_id) VALUES(#{userId})")
    int ensureStreak(@Param("userId") String userId);

    // The row lock serializes same-user check-ins, monthly cap and milestone awards.
    @Select("SELECT streak_start,last_day,current_streak FROM checkin_streaks "
            + "WHERE user_id=#{userId} FOR UPDATE")
    Map<String, Object> lockStreak(@Param("userId") String userId);

    @Insert("INSERT IGNORE INTO daily_checkins(user_id,checkin_day) VALUES(#{userId},#{day})")
    int insertDay(@Param("userId") String userId, @Param("day") Date day);

    @Update("UPDATE checkin_streaks SET streak_start=#{start},last_day=#{day},"
            + "current_streak=#{streak},longest_streak=GREATEST(longest_streak,#{streak}),"
            + "total_days=total_days+1 WHERE user_id=#{userId}")
    int updateStreak(@Param("userId") String userId, @Param("start") Date start,
                     @Param("day") Date day, @Param("streak") int streak);

    @Select("SELECT COALESCE(SUM(awarded_count),0) FROM checkin_awards WHERE user_id=#{userId} "
            + "AND award_day>=#{from} AND award_day<#{until}")
    int monthlyAwardCount(@Param("userId") String userId, @Param("from") Date from,
                          @Param("until") Date until);

    @Insert("INSERT IGNORE INTO checkin_awards(user_id,streak_start,milestone,award_day,awarded_count) "
            + "VALUES(#{userId},#{start},#{milestone},#{day},#{count})")
    int insertAward(@Param("userId") String userId, @Param("start") Date start,
                    @Param("milestone") int milestone, @Param("day") Date day,
                    @Param("count") int count);

    @Select("SELECT DAY(checkin_day) FROM daily_checkins WHERE user_id=#{userId} "
            + "AND checkin_day>=#{from} AND checkin_day<#{until} ORDER BY checkin_day")
    List<Integer> daysInMonth(@Param("userId") String userId, @Param("from") Date from,
                              @Param("until") Date until);

    @Select("SELECT last_day,current_streak,longest_streak,total_days FROM checkin_streaks "
            + "WHERE user_id=#{userId}")
    Map<String, Object> state(@Param("userId") String userId);

    @Select("SELECT s.user_id AS userId,u.display_name AS displayName,s.current_streak AS streak "
            + "FROM checkin_streaks s JOIN users u ON u.id=s.user_id "
            + "WHERE s.last_day>=#{since} "
            + "ORDER BY s.current_streak DESC,s.last_day ASC,s.user_id ASC LIMIT #{limit}")
    List<Map<String, Object>> leaderboard(@Param("since") Date since, @Param("limit") int limit);

    @Select("SELECT milestone,voucher_count AS voucherCount,validity_days AS validityDays,enabled,"
            + "NULL AS effectiveAt,'active' AS state FROM checkin_reward_rules "
            + "UNION ALL SELECT milestone,voucher_count AS voucherCount,validity_days AS validityDays,enabled,"
            + "effective_at AS effectiveAt,'scheduled' AS state "
            + "FROM checkin_reward_rule_changes WHERE effective_at>UTC_TIMESTAMP(6) "
            + "ORDER BY milestone,effectiveAt")
    List<Map<String, Object>> rules();

    @Select("SELECT base.milestone,"
            + "COALESCE(change_rule.voucher_count,base.voucher_count) AS voucher_count,"
            + "COALESCE(change_rule.validity_days,base.validity_days) AS validity_days,"
            + "COALESCE(change_rule.enabled,base.enabled) AS enabled "
            + "FROM checkin_reward_rules base LEFT JOIN checkin_reward_rule_changes change_rule "
            + "ON change_rule.milestone=base.milestone "
            + "AND change_rule.effective_at=(SELECT MAX(c.effective_at) "
            + "FROM checkin_reward_rule_changes c "
            + "WHERE c.milestone=base.milestone AND c.effective_at<=UTC_TIMESTAMP(6)) "
            + "ORDER BY base.milestone")
    List<Map<String, Object>> effectiveRules();

    @Insert("INSERT IGNORE INTO checkin_reward_rules(milestone,voucher_count,validity_days,enabled) "
            + "VALUES(#{milestone},#{count},#{days},FALSE)")
    int ensureRule(@Param("milestone") int milestone, @Param("count") int count,
                   @Param("days") int days);

    @Insert("INSERT INTO checkin_reward_rule_changes(milestone,effective_at,voucher_count,validity_days,enabled) "
            + "VALUES(#{milestone},#{effectiveAt},#{count},#{days},#{enabled})")
    int scheduleRule(@Param("milestone") int milestone, @Param("effectiveAt") LocalDateTime effectiveAt,
                     @Param("count") int count, @Param("days") int days,
                     @Param("enabled") boolean enabled);
}
