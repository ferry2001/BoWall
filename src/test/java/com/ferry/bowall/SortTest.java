package com.ferry.bowall;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ferry.bowall.dto.MessageDto;
import com.fasterxml.jackson.core.type.TypeReference;
import java.util.ArrayList;

import com.ferry.bowall.entity.Message;
import com.ferry.bowall.enums.Message.MessageIsDel;
import com.ferry.bowall.enums.Message.MessageIsRead;
import com.ferry.bowall.service.MessageService;
import com.ferry.bowall.service.UserService;
import org.junit.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

import java.time.LocalDateTime;

@SpringBootTest
public class SortTest {

    @Autowired
    private MessageService messageService;

    @Autowired
    private UserService userService;

    @Test
    public void sortBubble() throws JsonProcessingException {
        ArrayList<MessageDto> messageDtoList = new ArrayList<>();
        /*
         private String id;
    private String senderAccount;
    private String recipientAccount;
    private String content;
    private MessageIsRead isRead;
    private MessageIsDel isDel;
    private LocalDateTime updateDate;
        * */
        messageDtoList.add(new MessageDto(
                new Message("10", "AKA", "fefylosfahor", "hello", MessageIsRead.no, MessageIsDel.no,
                        LocalDateTime.parse("2024-01-21T15:18:48")),
                "AKA", "AKA",
                "http://47.98.224.129:8080/images/340e60bc-846d-47dc-9516-2a73f3c7152e.png",
                (long)0));

        messageDtoList.add(new MessageDto(
                new Message("6864de45-d1df-4a5b-a87a-dcca16756e8e", "bbjj", "fefylosfahor", "it need test", MessageIsRead.no, MessageIsDel.no,
                        LocalDateTime.parse("2023-12-19T20:32:33")),
                "bbjj", "百变酒精",
                "http://47.98.224.129:8080/images/29722df3-c8ac-439f-8443-1c02bf80eaad.png",
                (long)25));

        messageDtoList.add(new MessageDto(
                new Message("ba7a73b5-2859-4c2a-a709-d32a2bb8564e", "1", "fefylosfahor", "n", MessageIsRead.no, MessageIsDel.no,
                        LocalDateTime.parse("2024-01-20T19:32:27")),
                "1", "root",
                "http://47.98.224.129:8080/images/5690dfab-58ad-45b1-aaa3-d728a9729ae0.png",
                0L));

        messageDtoList.add(new MessageDto(
                new Message("11", "test", "fefylosfahor", "hello world", MessageIsRead.no, MessageIsDel.no,
                        LocalDateTime.parse("2024-01-21T15:18:48")),
                "test", "test",
                "http://47.98.224.129:8080/images/7af4af36-ecf5-4736-b715-f74a70212590.png",
                0L));

        messageDtoList.add(new MessageDto(
                new Message("904bc9b9-a546-40c3-b915-c194e77a2d75", "fefylosfahor", "fefylosfahor", "hi", MessageIsRead.no, MessageIsDel.no,
                        LocalDateTime.parse("2023-12-26T19:38:59")),
                "fefylosfahor", "ferry",
                "http://47.98.224.129:8080/images/8049d14b-d360-41ed-9456-71aeca4f61d7.png",
                0L));


        for (MessageDto messageDto : messageDtoList) {
            System.out.println(messageDto.getMessage().getUpdateDate());
        }

        for (int i = 0; i < messageDtoList.size() - 1; i++) {
            int maxIndex = i;
            LocalDateTime updateDate_max = messageDtoList.get(maxIndex).getMessage().getUpdateDate();

            for (int j = i + 1; j < messageDtoList.size(); j++) {
                LocalDateTime updateDate_j = messageDtoList.get(j).getMessage().getUpdateDate();
                // 查找最大（最新）的更新日期
                if (updateDate_j.isAfter(updateDate_max)) {
                    maxIndex = j;
                    updateDate_max = updateDate_j;
                }
            }

            // 如果找到最大元素，与索引处 i 的元素交换
            if (maxIndex != i) {
                MessageDto temp = messageDtoList.get(i);
                messageDtoList.set(i, messageDtoList.get(maxIndex));
                messageDtoList.set(maxIndex, temp);
            }
        }

        System.out.println("================");
        for (MessageDto messageDto : messageDtoList) {
            System.out.println(messageDto.getMessage().getUpdateDate());
        }
    }
}
