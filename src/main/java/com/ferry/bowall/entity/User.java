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
    /** 国家代码，如 CN、US；为空时由手机号规则推断。 */
    private String country;
    private String nativeLanguage;
    /** 英语阅读能力 0~1；英语母语用户为 1。 */
    private Double englishLevel;

    private LocalDateTime UpdateTime;
}
