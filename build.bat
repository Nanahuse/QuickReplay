@REM Copyright (c) 2022 Nanahuse
@REM This software is released under the MIT License
@REM https://github.com/Nanahuse/QuickReplay/blob/main/LICENSE


pyinstaller ./src/quick_replay_controller.py ^
--name QuickReplay ^
-p ./;./src ^
--add-binary ./assets/forward.png;./assets ^
--add-binary ./assets/rewind.png;./assets ^
--add-binary ./assets/next.png;./assets ^
--add-binary ./assets/prev.png;./assets ^
--add-binary ./assets/play.png;./assets ^
--add-binary ./assets/pause.png;./assets ^
--add-binary ./assets/record.png;./assets ^
--add-binary ./assets/stop.png;./assets ^
--add-data ./assets/default_setting.json;./assets ^
--add-data ./assets/software_infomation.json;./assets ^
--add-data ./tmp_video/memo.txt;./tmp_video ^
--add-data ./LICENSE;./ ^
--add-data ./LICENSE_ThirdParty.md;./ ^
--add-data ./assets/LICENSE_ThirdParty.json;./assets ^
--noconsole ^
--clean ^
-y
