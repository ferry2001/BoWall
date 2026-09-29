package com.ferry.bowall.entity;

import lombok.Data;

import java.time.LocalDateTime;

/** 一位用户在一次浏览会话中对一条动态累计的有效停留时长。 */
@Data
public class PostDwell {
    private String id;
    private String postId;
    private String account;
    private String sessionId;
    private Long dwellSeconds;
    private LocalDateTime updateDate;
}
