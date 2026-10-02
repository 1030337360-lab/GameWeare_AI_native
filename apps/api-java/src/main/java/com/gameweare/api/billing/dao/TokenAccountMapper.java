package com.gameweare.api.billing.dao;

import java.util.Map;
import java.util.List;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

/** Token balance and ledger SQL. Spring's transaction manager binds mapper calls to the same connection. */
@Mapper
public interface TokenAccountMapper {
    @Select("SELECT balance,reserved,version FROM token_accounts WHERE user_id=#{userId}")
    Map<String, Object> findAccount(@Param("userId") String userId);

    // Former JDBC query used the same SELECT ... FOR UPDATE; the row lock is held through @Transactional.
    @Select("SELECT balance,reserved,version FROM token_accounts WHERE user_id=#{userId} FOR UPDATE")
    Map<String, Object> lockAccount(@Param("userId") String userId);

    @Select("SELECT user_id,amount FROM token_ledger WHERE job_id=#{jobId} AND entry_type=#{type}")
    Map<String, Object> findLedger(@Param("jobId") String jobId, @Param("type") String type);

    @Update("UPDATE token_accounts SET balance=balance-#{amount},reserved=reserved+#{amount},version=version+1 "
            + "WHERE user_id=#{userId}")
    int reserve(@Param("userId") String userId, @Param("amount") long amount);

    @Update("UPDATE token_accounts SET reserved=reserved-#{reserved},balance=balance+#{refunded},version=version+1 "
            + "WHERE user_id=#{userId}")
    int release(@Param("userId") String userId, @Param("reserved") long reserved,
                @Param("refunded") long refunded);

    @Insert("INSERT INTO token_ledger(id,user_id,job_id,entry_type,amount,created_at) "
            + "VALUES(#{id},#{userId},#{jobId},#{type},#{amount},CURRENT_TIMESTAMP)")
    int insertLedger(@Param("id") String id, @Param("userId") String userId,
                     @Param("jobId") String jobId, @Param("type") String type, @Param("amount") long amount);

    @Select("""
            SELECT a.user_id,a.balance,a.reserved,
                   COALESCE(SUM(CASE l.entry_type
                       WHEN 'GRANT' THEN l.amount
                       WHEN 'RESERVE' THEN -l.amount
                       WHEN 'REFUND' THEN l.amount ELSE 0 END),0) AS expected_balance,
                   COALESCE(SUM(CASE l.entry_type
                       WHEN 'RESERVE' THEN l.amount
                       WHEN 'SETTLE' THEN -l.amount
                       WHEN 'REFUND' THEN -l.amount ELSE 0 END),0) AS expected_reserved
            FROM token_accounts a LEFT JOIN token_ledger l ON l.user_id=a.user_id
            GROUP BY a.user_id,a.balance,a.reserved
            HAVING a.balance<0 OR a.reserved<0
                OR a.balance<>expected_balance OR a.reserved<>expected_reserved
            LIMIT 100
            """)
    List<Map<String, Object>> accountMismatches();
}
