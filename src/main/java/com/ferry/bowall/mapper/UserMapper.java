package com.ferry.bowall.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.ferry.bowall.entity.User;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
@Mapper
public interface UserMapper extends BaseMapper<User> {

    void updateUser(User user);

    @Select("SELECT * FROM bowall.user")
    List<User> getUserList();

    User getUser(String account);

    List<User> friends(String account);

}
