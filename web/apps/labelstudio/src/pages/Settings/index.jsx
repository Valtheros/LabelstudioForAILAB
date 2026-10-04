import { SidebarMenu } from "../../components/SidebarMenu/SidebarMenu";
import { GeneralSettings } from "./GeneralSettings";
import { LabelingSettings } from "./LabelingSettings";
import "./settings.scss";

export const MenuLayout = ({ children, ...routeProps }) => {
  return (
    <SidebarMenu
      menuItems={[
        GeneralSettings,
        LabelingSettings,
      ].filter(Boolean)}
      path={routeProps.match.url}
      children={children}
    />
  );
};

const pages = {
  LabelingSettings,
};

export const SettingsPage = {
  title: "Settings",
  path: "/settings",
  exact: true,
  layout: MenuLayout,
  component: GeneralSettings,
  pages,
};
