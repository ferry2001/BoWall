package com.ferry.bowall.entity;

import com.ferry.bowall.enums.Notification.NotificationStatus;
import com.ferry.bowall.enums.Notification.NotificationType;
import lombok.Data;

import java.time.LocalDateTime;

@Data
public class Notification {
    private String id;
    private String account;
    private String commentsId;
    private String messageId;
    private NotificationStatus status;
    private NotificationType type;
    private LocalDateTime updateDate;
}
