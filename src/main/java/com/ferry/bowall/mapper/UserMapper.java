package com.ferry.bowall.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.ferry.bowall.entity.User;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Map;
import java.util.Set;

@Repository
@Mapper
public interface UserMapper extends BaseMapper<User> {

    void updateUser(User user);

    @Select("SELECT * FROM user")
    List<User> getUserList();

    User getUser(String account);

    @Select("SELECT name FROM user WHERE account = #{account}")
    String getUserName(String account);

    @Select("SELECT avatar FROM user WHERE account = #{account}")
    String getAvatar(String account);

    List<User> friends(String account);

    List<User> getUsers(Set<String> accounts);
}
