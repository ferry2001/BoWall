package com.ferry.bowall.entity;

import lombok.Data;

import java.time.LocalDateTime;

@Data
public class Posts {
    private String id;
    private String account;
    private String text;
    private Long viewCount;
    private LocalDateTime updateDate;
}
