type UserAvatarProps = {
  name: string;
  initials: string;
};

export default function UserAvatar({ name, initials }: UserAvatarProps) {
  return <span className="user-avatar" aria-label={name}>{initials}</span>;
}
