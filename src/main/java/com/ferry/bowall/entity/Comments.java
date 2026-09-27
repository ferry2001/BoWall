package com.ferry.bowall.entity;

import com.ferry.bowall.enums.Comments.CommentsIsDel;
import com.ferry.bowall.enums.Comments.CommentsIsRead;
import com.ferry.bowall.enums.Message.MessageIsDel;
import com.ferry.bowall.enums.Message.MessageIsRead;
import lombok.Data;

import java.time.LocalDateTime;

@Data
public class Comments {
    private String id;
    private String postsId;
    private String account;
    private String text;
    private LocalDateTime updateDate;
    private CommentsIsRead isRead;
    private CommentsIsDel isDel;

}
