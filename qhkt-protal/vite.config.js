// 项目配置页面
import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import svgLoader from 'vite-svg-loader';
import vueJsx from '@vitejs/plugin-vue-jsx';
import path from 'path';

const CWD = process.cwd();

//配置参考 https://vitejs.dev/config/
export default defineConfig((mode) => {
  // const { VITE_BASE_URL } = loadEnv(mode, CWD);
  return {
    base: './',
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
    },
    plugins: [
      vue(),
      vueJsx(),
      svgLoader()
    ],
    server: {
      port: 18082,
      host: '0.0.0.0',
      proxy: {
        '/as': {
          target: 'http://api.qhkt.com',
          changeOrigin: true,
        },
        '/us': {
          target: 'http://api.qhkt.com',
          changeOrigin: true,
        },
        '/ais': {
          target: 'http://api.qhkt.com',
          changeOrigin: true,
        },
        '/cs': {
          target: 'http://api.qhkt.com',
          changeOrigin: true,
        },
        '/ss': {
          target: 'http://api.qhkt.com',
          changeOrigin: true,
        },
        '/ls': {
          target: 'http://api.qhkt.com',
          changeOrigin: true,
        },
        '/ms': {
          target: 'http://api.qhkt.com',
          changeOrigin: true,
        },
        '/prs': {
          target: 'http://api.qhkt.com',
          changeOrigin: true,
        },
        '/es': {
          target: 'http://api.qhkt.com',
          changeOrigin: true,
        },
        '/ts': {
          target: 'http://api.qhkt.com',
          changeOrigin: true,
        },
        '/sms': {
          target: 'http://api.qhkt.com',
          changeOrigin: true,
        },
        '/rs': {
          target: 'http://api.qhkt.com',
          changeOrigin: true,
        },
        '/img-tx': {
          target: 'https://wisehub-1312394356.cos.ap-shanghai.myqcloud.com',
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/img-tx/, ''),
        },
        '/mock/3359':{
          target: 'http://172.17.0.137:8321/mock/3359',
          changeOrigin: true,
        }
      }
    },
  }
})
