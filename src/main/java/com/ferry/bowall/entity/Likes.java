package com.ferry.bowall.entity;

import lombok.Data;

import java.time.LocalDateTime;

@Data
public class Likes {
    private String id;
    private String account;
    private String postId;
    private LocalDateTime updateDate;
}
