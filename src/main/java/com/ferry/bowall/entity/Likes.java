package com.ferry.bowall.entity;

import lombok.Data;

import java.time.LocalDateTime;

@Data
public class Likes {
    private String id;
    private String account;
    private String postId;
    /** 是否已被动态作者查看，用于互动消息未读提醒。 */
    private String isRead;
    private LocalDateTime updateDate;
}
