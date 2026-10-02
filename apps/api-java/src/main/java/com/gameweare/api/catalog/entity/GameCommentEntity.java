package com.gameweare.api.catalog.entity;

import java.sql.Timestamp;

/** Read model for a comment joined with its author's display name. */
public record GameCommentEntity(String id, String userId, String content,
                                Timestamp createdAt, String displayName) {}
