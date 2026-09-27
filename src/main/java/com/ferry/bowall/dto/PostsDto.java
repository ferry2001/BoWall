package com.ferry.bowall.dto;

import com.ferry.bowall.entity.Comments;
import com.ferry.bowall.entity.Image;
import com.ferry.bowall.entity.Posts;
import com.ferry.bowall.entity.User;
import lombok.Data;
import lombok.EqualsAndHashCode;

import java.util.ArrayList;
import java.util.List;

@Data
@EqualsAndHashCode(callSuper = false)
public class PostsDto extends Posts {
    private User user;
    private List<Image> images = new ArrayList<>();
    private List<CommentsDto> comments = new ArrayList<>();
    private Integer isLike;
}
