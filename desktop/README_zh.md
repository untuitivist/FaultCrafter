# Windows 打包入口

正式业务代码位于faultcrafter包；CLI与浏览器GUI调用相同服务。推荐先在Python环境验证：

```console
python -m pip install -e ".[training,desktop]"
python -m faultcrafter gui --model-root C:\models\faultcrafter\compact
```

发布32包必须含shared_generator.pt和四台内置设备各自的device_lora.pt、signal_profile.json。打包时核对release_id，不能拿留出实验的某一个子模型替代全数据发布包。

```bat
set FAULTCRAFTER_PYTHON=python
set FAULTCRAFTER_MODEL_ROOT=C:\models\faultcrafter\compact
desktop\build_exe.cmd
```

不设置模型路径时，在源码工作区查找outputs/deployment/experiment32_full_data_v1/compact。已有dist目标目录不会覆盖。

CPU构建使用desktop/setup_cpu_build_env.cmd与desktop/build_cpu_lite.cmd。安装包采用PyInstaller onedir，分发时保留EXE旁的_internal目录。新设备接入需要training依赖，已纳入构建依赖。

原Tkinter单设备界面已归档。desktop/web_server.py仅作为冻结程序和原启动命令的转发入口；HTML、JavaScript与训练配方从Python包内读取。旧EXE不会随源码修改自动更新。
