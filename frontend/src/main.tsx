import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { ConfigProvider, App as AntApp } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import dayjs from 'dayjs'
import 'dayjs/locale/zh-cn'
import App from './App'
import './index.css'

dayjs.locale('zh-cn')

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: '#315EAD',
          colorInfo: '#315EAD',
          colorSuccess: '#2F7D5B',
          colorWarning: '#B86A20',
          colorError: '#C23A3A',
          colorText: '#172033',
          colorTextSecondary: '#687386',
          colorBorder: '#E1E7EF',
          colorBgLayout: '#F6F8FB',
          colorBgContainer: '#FFFFFF',
          colorFillAlter: '#F4F7FB',
          borderRadius: 2,
          borderRadiusLG: 0,
          controlHeight: 36,
          fontSize: 14,
        },
        components: {
          Layout: {
            headerHeight: 64,
            headerPadding: 0,
            siderBg: '#FFFFFF',
            bodyBg: '#F6F8FB',
          },
          Card: {
            borderRadiusLG: 0,
            boxShadowTertiary: 'none',
          },
          Button: {
            borderRadius: 2,
            controlHeight: 36,
          },
          Table: {
            headerBg: '#F7F9FC',
            headerColor: '#687386',
            borderColor: '#E1E7EF',
          },
          Menu: {
            itemBg: '#FFFFFF',
            subMenuItemBg: '#FFFFFF',
            itemColor: '#526071',
            itemHoverColor: '#172033',
            itemHoverBg: '#F4F7FB',
            itemSelectedColor: '#315EAD',
            itemSelectedBg: '#EBF2FD',
            groupTitleColor: '#8A96A6',
          },
          Tag: {
            borderRadiusSM: 2,
          },
        },
      }}
    >
      <AntApp>
        <App />
      </AntApp>
    </ConfigProvider>
  </StrictMode>,
)
