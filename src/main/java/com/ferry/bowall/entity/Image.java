package com.ferry.bowall.entity;


import com.ferry.bowall.enums.Image.ImageIsCover;
import lombok.Data;
import org.springframework.beans.factory.annotation.Qualifier;

import java.time.LocalDateTime;

@Data
@Qualifier
public class Image {
    private String account;
    private String url;
    private String postsId;
    private String width;
    private String height;
    private LocalDateTime updateDate;
    private ImageIsCover isCover;
}
