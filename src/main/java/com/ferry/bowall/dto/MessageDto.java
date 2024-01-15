package com.ferry.bowall.dto;

import com.ferry.bowall.entity.Message;
import lombok.Data;

@Data
public class MessageDto {
    private Message message;
    private String account;
    private String name;
    private String avatar;

    private Long count;
}
