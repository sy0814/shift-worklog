package rs.workrecord.app;

import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;

import com.getcapacitor.BridgeActivity;

/**
 * App 外壳：本地页面填服务器地址后打开服务器上的系统网页（证书已打包，见 res/xml/network_security_config.xml）。
 * 网页里的下载（例如新版本安装包 http://服务器/app.apk、导出的 Excel）交给手机浏览器 / 系统去下载，WebView 自己不会下载。
 */
public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getBridge().getWebView().setDownloadListener((url, userAgent, contentDisposition, mimetype, contentLength) -> {
            try {
                // 新版本安装包：手机浏览器不认这个证书，改走 HTTP（服务器 80 端口提供 /app.apk）
                if (url.startsWith("https://") && Uri.parse(url).getPath() != null && Uri.parse(url).getPath().endsWith("/app.apk")) {
                    url = "http://" + url.substring("https://".length());
                }
                startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)));
            } catch (Exception ignored) {
                // 没有能打开链接的应用：什么都不做
            }
        });
    }
}
