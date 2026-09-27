package com.ferry.bowall.enums.Message;

import com.baomidou.mybatisplus.annotation.EnumValue;
import lombok.Getter;

@Getter
public enum MessageIsDel {
    no("no", "no"),
    yes("yes", "yes");


    MessageIsDel(String value, String desc) {
        this.value = value;
        this.desc = desc;
    }

    @EnumValue
    private final String value;
    private final String desc;
}
