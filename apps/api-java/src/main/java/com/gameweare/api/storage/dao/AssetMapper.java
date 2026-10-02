package com.gameweare.api.storage.dao;

import java.util.Map;
import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

@Mapper
public interface AssetMapper {
    @Insert("INSERT INTO assets(id,owner_id,kind,bucket,object_key,content_type,size_bytes,public_url,created_at) "
            + "VALUES(#{id},#{ownerId},'upload',#{bucket},#{objectKey},#{contentType},#{sizeBytes},"
            + "#{publicUrl},UTC_TIMESTAMP())")
    int insertUpload(@Param("id") String id, @Param("ownerId") String ownerId,
                     @Param("bucket") String bucket, @Param("objectKey") String objectKey,
                     @Param("contentType") String contentType, @Param("sizeBytes") long sizeBytes,
                     @Param("publicUrl") String publicUrl);

    @Select("SELECT bucket,object_key FROM assets WHERE id=#{assetId} AND owner_id=#{userId} "
            + "AND kind='upload' FOR UPDATE")
    Map<String, Object> lockUpload(@Param("assetId") String assetId, @Param("userId") String userId);

    @Select("SELECT COUNT(*) FROM create_job_inputs WHERE asset_id=#{assetId}")
    int usageCount(@Param("assetId") String assetId);

    @Delete("DELETE FROM assets WHERE id=#{assetId} AND owner_id=#{userId} AND kind='upload'")
    int deleteUpload(@Param("assetId") String assetId, @Param("userId") String userId);

    @Select("SELECT bucket,object_key,content_type FROM assets "
            + "WHERE id=#{assetId} AND owner_id=#{userId} AND kind='upload'")
    Map<String, Object> ownedUpload(@Param("assetId") String assetId, @Param("userId") String userId);

    @Select("SELECT cover_object_key,title,description FROM games "
            + "WHERE slug=#{slug} AND publish_status='published' AND visibility='public'")
    Map<String, Object> publicCover(@Param("slug") String slug);

    @Select("SELECT content_type FROM assets WHERE object_key=#{objectKey} AND kind='cover' LIMIT 1")
    String coverContentType(@Param("objectKey") String objectKey);
}
