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

    public MessageDto() {
    }

    public MessageDto(Message message, String account, String name, String avatar, Long count) {
        this.message = message;
        this.account = account;
        this.name = name;
        this.avatar = avatar;
        this.count = count;
    }
}
