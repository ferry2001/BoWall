package com.ferry.bowall.entity;

import lombok.Data;

import java.time.LocalDateTime;

@Data
public class Posts {
    private String id;
    private String account;
    private String text;
    private Long viewCount;
    /** 0: ordinary post; 1: editor-selected featured post. */
    private Integer isFeatured;
    private LocalDateTime updateDate;
}
