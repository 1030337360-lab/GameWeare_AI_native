package com.gameweare.api.catalog.dao;

import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

/** Idempotent startup fixture; every insert is guarded by a stable ID or unique key. */
@Mapper
public interface BuiltInGameMapper {
    @Select("SELECT id FROM games WHERE slug=#{slug}")
    String gameIdBySlug(@Param("slug") String slug);

    @Select("SELECT COUNT(*) FROM games WHERE id=#{gameId} "
            + "AND publish_status='published' AND visibility='public'")
    int publicGameCount(@Param("gameId") String gameId);

    @Insert("INSERT IGNORE INTO users(id,email,password_hash,display_name,role) "
            + "VALUES(#{id},#{email},#{passwordHash},#{displayName},'user')")
    int insertAuthor(@Param("id") String id, @Param("email") String email,
                     @Param("passwordHash") String passwordHash, @Param("displayName") String displayName);

    @Select("SELECT id FROM users WHERE email=#{email}")
    String authorIdByEmail(@Param("email") String email);

    @Insert("INSERT IGNORE INTO games(id,slug,title,description,author_id,publish_status,visibility) "
            + "VALUES(#{id},#{slug},#{title},#{description},#{authorId},'draft','private')")
    int insertGame(@Param("id") String id, @Param("slug") String slug, @Param("title") String title,
                   @Param("description") String description, @Param("authorId") String authorId);

    @Insert("INSERT IGNORE INTO game_versions(id,game_id,version_no,entry_object_key,runtime,"
            + "build_status,safety_status,entry_file,storage_prefix) "
            + "VALUES(#{id},#{gameId},1,#{entryObjectKey},'iframe-html5','passed','passed','index.html',#{prefix})")
    int insertVersion(@Param("id") String id, @Param("gameId") String gameId,
                      @Param("entryObjectKey") String entryObjectKey, @Param("prefix") String prefix);

    @Insert("INSERT IGNORE INTO assets(id,owner_id,game_id,version_id,kind,bucket,object_key,content_type,size_bytes) "
            + "VALUES(#{id},#{ownerId},#{gameId},#{versionId},'html',#{bucket},#{objectKey},"
            + "#{contentType},#{sizeBytes})")
    int insertAsset(@Param("id") String id, @Param("ownerId") String ownerId,
                    @Param("gameId") String gameId, @Param("versionId") String versionId,
                    @Param("bucket") String bucket, @Param("objectKey") String objectKey,
                    @Param("contentType") String contentType, @Param("sizeBytes") long sizeBytes);

    @Update("UPDATE games SET current_version_id=#{versionId},publish_status='published',visibility='public',"
            + "published_at=COALESCE(published_at,UTC_TIMESTAMP(6)) "
            + "WHERE id=#{gameId} AND slug=#{slug} AND author_id=#{authorId} AND current_version_id IS NULL")
    int publish(@Param("versionId") String versionId, @Param("gameId") String gameId,
                @Param("slug") String slug, @Param("authorId") String authorId);
}
