package com.ferry.bowall.enums.Comments;

import com.baomidou.mybatisplus.annotation.EnumValue;

public enum CommentsIsRead {
    no("no", "no"),
    yes("yes", "yes");


    CommentsIsRead(String value, String desc) {
        this.value = value;
        this.desc = desc;
    }

    @EnumValue
    private final String value;
    private final String desc;
}
