package com.gameweare.api.auth.dao;

import java.sql.Timestamp;
import java.util.Map;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

/** MySQL access for local login and session state. SQL stays beside each DAO method for review. */
@Mapper
public interface AuthMapper {
    @Insert("INSERT INTO users(id,email,password_hash,display_name,role,last_login_at,created_at) "
            + "VALUES(#{id},#{email},#{passwordHash},#{displayName},'user',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)")
    int insertUser(@Param("id") String id, @Param("email") String email,
                   @Param("passwordHash") String passwordHash, @Param("displayName") String displayName);

    @Insert("INSERT INTO token_accounts(user_id,balance,reserved,version) VALUES(#{userId},#{balance},0,0)")
    int insertAccount(@Param("userId") String userId, @Param("balance") long balance);

    @Insert("INSERT INTO token_ledger(id,user_id,job_id,entry_type,amount,created_at) "
            + "VALUES(#{id},#{userId},#{jobId},'GRANT',#{amount},CURRENT_TIMESTAMP)")
    int insertStarterGrant(@Param("id") String id, @Param("userId") String userId,
                           @Param("jobId") String jobId, @Param("amount") long amount);

    @Select("SELECT id,email,password_hash,display_name,role FROM users WHERE email=#{email}")
    Map<String, Object> findLoginUser(@Param("email") String email);

    @Update("UPDATE users SET last_login_at=CURRENT_TIMESTAMP WHERE id=#{id}")
    int touchLogin(@Param("id") String id);

    @Update("UPDATE user_sessions SET revoked_at=CURRENT_TIMESTAMP "
            + "WHERE token_hash=#{tokenHash} AND revoked_at IS NULL")
    int revokeSession(@Param("tokenHash") String tokenHash);

    @Select("SELECT u.id,u.email,u.display_name,u.avatar_url,u.role,u.last_login_at,s.expires_at,s.created_at "
            + "FROM user_sessions s JOIN users u ON u.id=s.user_id "
            + "WHERE s.token_hash=#{tokenHash} AND s.revoked_at IS NULL AND s.expires_at > CURRENT_TIMESTAMP")
    Map<String, Object> findActiveSession(@Param("tokenHash") String tokenHash);

    @Update("UPDATE user_sessions SET expires_at=#{newExpiry} WHERE token_hash=#{tokenHash} "
            + "AND revoked_at IS NULL AND expires_at>UTC_TIMESTAMP(6) AND expires_at<#{newExpiry}")
    int extendSession(@Param("newExpiry") Timestamp newExpiry, @Param("tokenHash") String tokenHash);

    @Insert("INSERT INTO user_sessions(id,user_id,token_hash,expires_at) "
            + "VALUES(#{id},#{userId},#{tokenHash},#{expiresAt})")
    int insertSession(@Param("id") String id, @Param("userId") String userId,
                      @Param("tokenHash") String tokenHash, @Param("expiresAt") Timestamp expiresAt);

    @Select("SELECT user_id FROM oauth_accounts WHERE provider='google' AND provider_subject=#{subject}")
    String findGoogleUserId(@Param("subject") String subject);

    @Select("SELECT COUNT(*) FROM users WHERE id=#{id}")
    int countUserById(@Param("id") String id);

    @Select("SELECT id FROM users WHERE email=#{email}")
    String findUserIdByEmail(@Param("email") String email);

    @Select("SELECT COUNT(*) FROM users WHERE email=#{email}")
    int countUserByEmail(@Param("email") String email);

    @Insert("INSERT INTO users(id,email,password_hash,display_name,avatar_url,role,last_login_at) "
            + "VALUES(#{id},#{email},NULL,#{name},#{picture},'user',CURRENT_TIMESTAMP)")
    int insertGoogleUser(@Param("id") String id, @Param("email") String email,
                         @Param("name") String name, @Param("picture") String picture);

    @Insert("INSERT INTO oauth_accounts(provider,provider_subject,user_id,provider_email) "
            + "VALUES('google',#{subject},#{userId},#{email})")
    int insertGoogleAccount(@Param("subject") String subject, @Param("userId") String userId,
                            @Param("email") String email);

    @Update("UPDATE oauth_accounts SET provider_email=#{email} "
            + "WHERE provider='google' AND provider_subject=#{subject}")
    int updateGoogleEmail(@Param("email") String email, @Param("subject") String subject);

    @Update("UPDATE users SET last_login_at=CURRENT_TIMESTAMP,avatar_url=COALESCE(#{picture},avatar_url) WHERE id=#{id}")
    int touchGoogleLogin(@Param("picture") String picture, @Param("id") String id);

    @Select("SELECT id,email,display_name,avatar_url,role,last_login_at FROM users WHERE id=#{id}")
    Map<String, Object> findUserById(@Param("id") String id);
}
