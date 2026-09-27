package com.ferry.bowall.enums.Notification;

import com.baomidou.mybatisplus.annotation.EnumValue;
import lombok.Getter;

@Getter
public enum NotificationType {
    MESSAGE("message", "message"),
    COMMENTS("comments", "comments");

    NotificationType(String value, String desc) {
        this.value = value;
        this.desc = desc;
    }

    @EnumValue
    private final String value;
    private final String desc;
}
