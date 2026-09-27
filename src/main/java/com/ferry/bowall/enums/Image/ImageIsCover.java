package com.ferry.bowall.enums.Image;

import com.baomidou.mybatisplus.annotation.EnumValue;
import lombok.Getter;

@Getter
public enum ImageIsCover {
    no("no", "no"),
    yes("yes", "yes");


    ImageIsCover(String value, String desc) {
        this.value = value;
        this.desc = desc;
    }

    @EnumValue
    private final String value;
    private final String desc;
}
