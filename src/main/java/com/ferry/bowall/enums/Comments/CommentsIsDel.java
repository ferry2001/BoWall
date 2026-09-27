package com.ferry.bowall.enums.Comments;

import com.baomidou.mybatisplus.annotation.EnumValue;
import lombok.Getter;

@Getter
public enum CommentsIsDel {
    no("no", "no"),
    yes("yes", "yes");


    CommentsIsDel(String value, String desc) {
        this.value = value;
        this.desc = desc;
    }

    @EnumValue
    private final String value;
    private final String desc;
}
