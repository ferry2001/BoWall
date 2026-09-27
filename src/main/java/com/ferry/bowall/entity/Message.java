package com.ferry.bowall.entity;

import com.ferry.bowall.enums.Message.MessageIsDel;
import com.ferry.bowall.enums.Message.MessageIsRead;
import lombok.Data;

import java.time.LocalDateTime;

@Data
public class Message {
    private String id;
    private String senderAccount;
    private String recipientAccount;
    private String content;
    private MessageIsRead isRead;
    private MessageIsDel isDel;
    private LocalDateTime updateDate;

    public Message() {
    }

    public Message(String id, String senderAccount, String recipientAccount, String content, MessageIsRead isRead, MessageIsDel isDel, LocalDateTime updateDate) {
        this.id = id;
        this.senderAccount = senderAccount;
        this.recipientAccount = recipientAccount;
        this.content = content;
        this.isRead = isRead;
        this.isDel = isDel;
        this.updateDate = updateDate;
    }
}
