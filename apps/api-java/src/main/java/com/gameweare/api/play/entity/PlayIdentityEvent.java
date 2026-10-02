package com.gameweare.api.play.entity;

import java.sql.Timestamp;

/** Minimal persisted event data needed to rebuild approximate UV projections. */
public record PlayIdentityEvent(String gameId, String userId, String anonymousId, Timestamp createdAt) {}
