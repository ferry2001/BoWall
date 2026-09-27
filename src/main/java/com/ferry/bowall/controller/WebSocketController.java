package com.ferry.bowall.controller;

import com.ferry.bowall.common.R;
import com.ferry.bowall.entity.Message;
import org.springframework.messaging.handler.annotation.MessageMapping;
import org.springframework.messaging.handler.annotation.SendTo;
import org.springframework.stereotype.Controller;

@Controller
public class WebSocketController {
    @MessageMapping("/send/message")
    @SendTo("/topic/messages")
    public R<Message> sendMessage(Message message) {
        // 处理消息并返回响应
        return R.success(message);
    }
}