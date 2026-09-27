package com.ferry.bowall.controller;


import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.ferry.bowall.common.R;
import com.ferry.bowall.dto.MessageDto;
import com.ferry.bowall.entity.Message;
import com.ferry.bowall.entity.User;
import com.ferry.bowall.enums.Message.MessageIsDel;
import com.ferry.bowall.enums.Message.MessageIsRead;
import com.ferry.bowall.service.MessageService;
import com.ferry.bowall.service.UserService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

import java.time.LocalDateTime;
import java.util.*;
import java.util.stream.Collectors;


@RequestMapping("/message")
@RestController
@Slf4j
public class MessageController {
    @Autowired
    private MessageService messageService;

    @Autowired
    private UserService userService;

    @GetMapping("/getMessage")
    public R<Page<Message>> getMessage(String senderAccount, String recipientAccount, Long page, Long size) {
        LambdaQueryWrapper<Message> messageLambdaQueryWrapper = new LambdaQueryWrapper<>();
        messageLambdaQueryWrapper.eq(Message::getSenderAccount, senderAccount).eq(Message::getRecipientAccount, recipientAccount).or().eq(Message::getSenderAccount, recipientAccount).eq(Message::getRecipientAccount, senderAccount);
        messageLambdaQueryWrapper.orderByAsc(Message::getUpdateDate);
        Long count = messageService.count(messageLambdaQueryWrapper);
        //计算倒数页数
        page = (count % size == 0) ? (count / size) : (count / size + 1 - page);

        Page<Message> messagePage = new Page<>(page, size);
        Page<Message> messageData = messageService.page(messagePage, messageLambdaQueryWrapper);

        return R.success(messageData);
    }

    @PostMapping("/sendMessage")
    public R<Page<Message>> sendMessage(@RequestBody Map map) {
        System.out.println(map);
        String id = UUID.randomUUID().toString();
        String senderAccount = map.get("senderAccount").toString();
        String recipientAccount = map.get("recipientAccount").toString();
        String content = map.get("content").toString();
        LocalDateTime updateDate = LocalDateTime.now();

        Message message = new Message();
        message.setId(id);
        message.setSenderAccount(senderAccount);
        message.setRecipientAccount(recipientAccount);
        message.setContent(content);
        message.setUpdateDate(updateDate);
        message.setIsRead(MessageIsRead.no);
        message.setIsDel(MessageIsDel.no);
        messageService.save(message);

        Page<Message> messagePage = new Page<>();
        ArrayList<Message> messages = new ArrayList<>();
        messages.add(message);
        messagePage.setRecords(messages);

        return R.success(messagePage);
    }

    @PutMapping("updateIsRead")
    public R<String> updateIsRead(@RequestBody Map map) {
        String senderAccount = (String) map.get("senderAccount");
        String recipientAccount = (String) map.get("recipientAccount");
        LambdaUpdateWrapper<Message> messageLambdaUpdateWrapper = new LambdaUpdateWrapper<>();

        messageLambdaUpdateWrapper.eq(Message::getSenderAccount, senderAccount).eq(Message::getRecipientAccount, recipientAccount);
        messageLambdaUpdateWrapper.set(Message::getIsRead, "yes");

        messageService.update(messageLambdaUpdateWrapper);
        return R.success("updating isRead is completed");
    }


    @GetMapping("/notification")
    public R<ArrayList<MessageDto>> message(@RequestParam String account) {
        //get all message which is not deleted
        // where sender account or recipient account is self account.
        LambdaQueryWrapper<Message> messageLambdaQueryWrapper = new LambdaQueryWrapper<>();
        messageLambdaQueryWrapper
                .nested(i -> i.eq(Message::getRecipientAccount, account)
                        .or().eq(Message::getSenderAccount, account))
                .eq(Message::getIsDel, MessageIsDel.no)
                .orderByDesc(Message::getUpdateDate);
        List<Message> messages = messageService.list(messageLambdaQueryWrapper);

        //get user list of message notification
        HashSet<String> accounts = new HashSet<>();
        HashMap<String, Message> accountMessageMap = new HashMap<>();
        HashMap<String, Long> accountMessageCountMap = new HashMap<>();

        for (Message message : messages) {
            boolean isRecipient = account.equals(message.getRecipientAccount());
            boolean isUnread = message.getIsRead().equals(MessageIsRead.no);
            String tempAccount = isRecipient ? message.getSenderAccount() : message.getRecipientAccount();

            accounts.add(tempAccount);

            // 只计算当前用户作为接收者的消息数量
            if (isRecipient && isUnread) {
                // 如果已经见到过这个账户，消息计数加 1 ,如果是第一次看到此发送者账户，初始化消息计数为 1
                accountMessageCountMap.compute(
                        tempAccount, (key, val) -> (val == null) ? 1 : val + 1);

            }

            // 更新最新消息信息，根据更新日期保存最新消息。
            accountMessageMap.compute(tempAccount, (key, val) -> {
                if (val == null || message.getUpdateDate().isAfter(val.getUpdateDate())) {
                    return message;
                }
                return val;
            });
        }

        LambdaQueryWrapper<User> userLambdaQueryWrapper = new LambdaQueryWrapper<>();
        userLambdaQueryWrapper.in(User::getAccount, accounts);
        Map<String, User> users = userService.list(userLambdaQueryWrapper)
                .stream()
                .collect(Collectors.toMap(User::getAccount, User -> User));

        ArrayList<MessageDto> messageDtos = new ArrayList<>();

        for (String s : accounts) {
            MessageDto messageDto = new MessageDto();
            Message message = accountMessageMap.get(s);
            User user = users.get(s);

            messageDto.setMessage(message);
            messageDto.setAccount(s);
            messageDto.setName(user.getName());
            messageDto.setAvatar(user.getAvatar());
            messageDto.setCount(accountMessageCountMap.get(s));
            messageDtos.add(messageDto);
        }

        // 根据消息的日期排序
        Collections.sort(messageDtos, new Comparator<MessageDto>() {
            @Override
            public int compare(MessageDto o1, MessageDto o2) {
                // 我们假设 `getMessage().getUpdateDate()` 不会返回 null，如果有可能返回 null，则需要额外的 null 检查
                return o2.getMessage().getUpdateDate().compareTo(o1.getMessage().getUpdateDate());
            }
        });

        return R.success(messageDtos);
    }
}
