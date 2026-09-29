package com.ferry.bowall.entity;

import lombok.Data;

import java.time.LocalDateTime;

@Data
public class Posts {
    private String id;
    private String account;
    private String text;
    private Long viewCount;
    /** 冗余点赞计数，供信息流排序使用，避免对 likes 表逐帖 COUNT。 */
    private Long likeCount;
    /** 0: ordinary post; 1: editor-selected featured post. */
    private Integer isFeatured;
    private LocalDateTime updateDate;
}
