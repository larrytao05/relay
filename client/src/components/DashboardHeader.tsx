import Brand from "./Brand.tsx";
import Header from "./Header.tsx";
import UserAvatar from "./UserAvatar.tsx";

export default function DashboardHeader() {
  return (
    <Header className="dashboard-header">
      <Brand />
      <UserAvatar name="Larry Tao" initials="LT" />
    </Header>
  );
}
