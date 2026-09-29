package com.ferry.bowall.dto;

import com.ferry.bowall.entity.Likes;
import lombok.Data;

/** 点赞互动消息所需的展示数据。 */
@Data
public class LikeDto {
    private Likes like;
    private String account;
    private String name;
    private String userAvatar;
    private String postId;
    private String postsImage;
}
