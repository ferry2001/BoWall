package com.ferry.bowall.enums.Message;

import com.baomidou.mybatisplus.annotation.EnumValue;
import lombok.Getter;

@Getter
public enum MessageIsRead {
    no("no", "no"),
    yes("yes", "yes");


    MessageIsRead(String value, String desc) {
        this.value = value;
        this.desc = desc;
    }

    @EnumValue
    private final String value;
    private final String desc;
}
