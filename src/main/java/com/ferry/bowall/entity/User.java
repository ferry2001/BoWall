package com.ferry.bowall.entity;

import lombok.Data;
import java.time.LocalDateTime;

@Data
public class User {
    private String account;
    private String phone;
    private String name;
    private String password;
    private Integer status;
    private String avatar;
    private String sign;
    private String address;

    private LocalDateTime UpdateTime;
}
